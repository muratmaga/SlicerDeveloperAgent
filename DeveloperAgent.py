import os
import sys
import logging
import traceback
import contextlib
from io import StringIO
from datetime import datetime

# The standard Slicer imports
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import qt
import ctk
import vtk

# Try to import custom prompt configuration
try:
    # Look for prompts_config.py in Resources subdirectory
    # Slicer only loads modules from top-level, so config in subdirectory is safe
    import importlib.util
    module_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file = os.path.join(module_dir, "Resources", "prompts_config.py")
    
    if os.path.exists(prompt_file):
        spec = importlib.util.spec_from_file_location("prompts_config", prompt_file)
        slicer_prompts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(slicer_prompts)
        PROMPTS_LOADED = True
        PROMPTS_SOURCE = prompt_file
    else:
        PROMPTS_LOADED = False
        PROMPTS_SOURCE = "built-in"
except Exception as e:
    PROMPTS_LOADED = False
    PROMPTS_SOURCE = f"error: {str(e)}"
    logging.warning(f"Could not load Resources/prompts_config.py: {e}. Using built-in prompts.")

#
# DeveloperAgent
#

class DeveloperAgent(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Developer Agent"
        self.parent.categories = ["Developer Tools"]
        self.parent.dependencies = []  # No dependencies needed for script-only development
        self.parent.contributors = ["AI Assistant"]
        self.parent.helpText = "This module creates Python scripts for 3D Slicer."
        self.parent.acknowledgementText = "This module was developed with the assistance of AI."

#
# DeveloperAgentLogic
#
class DeveloperAgentLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self._outputCallback = None
        # Track last created/updated script for quick opening in Script Editor
        self.lastScriptNodeID = None
        self.lastScriptFilePath = None
        
        # Report prompt configuration source
        if PROMPTS_LOADED:
            logging.info(f"DeveloperAgent: Using custom prompts from {PROMPTS_SOURCE}")
        else:
            logging.info(f"DeveloperAgent: Using built-in prompts ({PROMPTS_SOURCE})")

    def _get_prompts(self, user_request=""):
        """Get prompt configuration from external file or use built-in fallback
        
        Args:
            user_request: The user's request text for RAG retrieval
        """
        if PROMPTS_LOADED:
            # Load Slicer documentation dynamically using RAG
            slicer_docs = self._load_slicer_documentation(user_request)
            
            # Append documentation to base prompt
            base_prompt = slicer_prompts.SYSTEM_PROMPT_BASE
            if slicer_docs:
                base_prompt += f"\n\n{slicer_docs}"
            
            return {
                'base': base_prompt,
                'script_requirements': slicer_prompts.SYSTEM_PROMPT_SCRIPT_REQUIREMENTS,
                'user_template': slicer_prompts.USER_PROMPT_TEMPLATE,
                'error_section': slicer_prompts.ERROR_ANALYSIS_SECTION,
                'ai_params': slicer_prompts.AI_PARAMETERS,
                'available_models': getattr(slicer_prompts, 'AVAILABLE_MODELS', []),
                'default_model': getattr(slicer_prompts, 'DEFAULT_MODEL', 'DeepSeek-R1'),
                'version': getattr(slicer_prompts, 'PROMPT_VERSION', 'unknown')
            }
        else:
            # Built-in fallback prompts (abbreviated for space)
            return self._get_builtin_prompts()
    
    def _load_slicer_documentation(self, user_request=""):
        """Load Slicer API documentation using RAG for targeted retrieval"""
        try:
            # Import RAG retriever from Resources directory
            import sys
            resources_dir = os.path.join(os.path.dirname(__file__), 'Resources')
            if resources_dir not in sys.path:
                sys.path.insert(0, resources_dir)
            
            from rag_retriever import SlicerRAG
            
            # Initialize RAG retriever
            rag = SlicerRAG()
            
            # Retrieve examples relevant to user's specific request
            if user_request:
                examples = rag.retrieve_examples(user_request, top_k=5)
            else:
                # No specific request yet, return empty
                examples = []
            
            # Format for prompt (limit to 3000 chars)
            formatted_docs = rag.format_for_prompt(examples, max_chars=3000)
            
            return formatted_docs
        except Exception as e:
            # If RAG fails, fall back to empty (won't break the agent)
            print(f"Warning: Could not load Slicer documentation via RAG: {e}")
            return ""
    
    def _get_builtin_prompts(self):
        """Built-in fallback prompts when external file not available"""
        return {
            'base': """You are an expert 3D Slicer Python developer. Generate working Python code.
            Use proven patterns. Output ONLY code, no markdown.""",
            'script_requirements': """
            Write standalone scripts for Slicer console.
            Include imports, error handling, and print statements.""",
            'user_template': """
USER REQUEST: {prompt}
{error_section}
CODE CONTEXT: {code_context}
Generate complete, executable code.""",
            'error_section': """PREVIOUS ATTEMPT FAILED:
{error_history}
Analyze the error and fix it.""",
            'ai_params': {'temperature': 0.3, 'max_tokens': 8000},
            'available_models': [
                ("DeepSeek-R1 (Recommended)", "DeepSeek-R1"),
                ("GPT-4o", "gpt-4o"),
                ("GPT-4o Mini", "gpt-4o-mini"),
            ],
            'default_model': 'DeepSeek-R1',
            'version': 'built-in-fallback'
        }

    def setOutputCallback(self, callback):
        """Set callback function to receive diagnostic output"""
        self._outputCallback = callback
    
    def setDebugIterations(self, iterations):
        """Set the number of debug iterations"""
        self._debugIterations = iterations
    
    def getDebugIterations(self):
        """Get the number of debug iterations"""
        return getattr(self, '_debugIterations', 2)
    
    def setModel(self, model):
        """Set the AI model to use"""
        self._model = model
    
    def getModel(self):
        """Get the AI model to use"""
        # Get default from configuration if available
        if PROMPTS_LOADED:
            default_model = getattr(slicer_prompts, 'DEFAULT_MODEL', 'DeepSeek-R1')
        else:
            default_model = 'DeepSeek-R1'
        return getattr(self, '_model', default_model)

    def loadScriptIntoScene(self, script_file_path):
        """Load a .py file into the MRML scene as a Python script text node using Script Editor conventions.
        - Reuses Script Editor storage helper if available
        - Ensures mimetype is set so Subject Hierarchy assigns correct icon/behavior
        - Avoids duplicate nodes if the script is already in the scene
        Returns: (node, message) where node is vtkMRMLTextNode or None.
        """
        try:
            if not os.path.exists(script_file_path):
                return None, f"File does not exist: {script_file_path}"

            # If a node already exists for this file, update and return it
            existing = slicer.mrmlScene.GetNodesByClass("vtkMRMLTextNode")
            try:
                for i in range(existing.GetNumberOfItems()):
                    n = existing.GetItemAsObject(i)
                    st = n.GetStorageNode()
                    if st and st.GetFileName() == script_file_path:
                        # Ensure correct attributes and refresh content from disk
                        with open(script_file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        n.SetText(content)
                        n.SetAttribute("mimetype", "text/x-python")
                        n.SetAttribute("customTag", "pythonFile")
                        # Ask SH to re-evaluate plugin (for icon/behavior)
                        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                        if shNode:
                            shNode.RequestOwnerPluginSearch(n)
                        # Persist last script references
                        self.lastScriptNodeID = n.GetID()
                        self.lastScriptFilePath = script_file_path
                        return n, "Updated existing script node"
            finally:
                existing.UnRegister(None) if existing is not None else None

            # Read content and create a new text node
            with open(script_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            text_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextNode')
            text_node.SetName(os.path.basename(script_file_path))
            text_node.SetText(content)
            text_node.SetAttribute("mimetype", "text/x-python")
            text_node.SetAttribute("customTag", "pythonFile")

            # Configure storage using Script Editor helper if available
            try:
                # Helper is defined in ScriptEditor module file
                from ScriptEditor import _createPythonScriptStorageNode  # type: ignore
                _createPythonScriptStorageNode(text_node, script_file_path)
            except Exception as e:
                # Fallback: create a basic text storage node with .py support
                storage_node = text_node.GetStorageNode()
                if not storage_node:
                    storage_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextStorageNode')
                storage_node.SetFileName(script_file_path)
                if hasattr(storage_node, "SetSupportedReadFileExtensions"):
                    storage_node.SetSupportedReadFileExtensions(["py"])
                if hasattr(storage_node, "SetSupportedWriteFileExtensions"):
                    storage_node.SetSupportedWriteFileExtensions(["py"])
                text_node.SetAndObserveStorageNodeID(storage_node.GetID())

            # Ensure Subject Hierarchy assigns correct plugin/icon
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            if shNode:
                shNode.RequestOwnerPluginSearch(text_node)

            # Persist last script references
            self.lastScriptNodeID = text_node.GetID()
            self.lastScriptFilePath = script_file_path

            return text_node, "Created new script node"
        except Exception as e:
            return None, f"Failed to load script into scene: {e}"

    def focusScriptInScriptEditor(self, nodeOrId):
        """Switch to Script Editor and select the provided text node.
        Retries briefly if the widget is not yet ready."""
        try:
            import qt
            # Resolve node
            node = None
            try:
                if hasattr(slicer, "vtkMRMLNode") and isinstance(nodeOrId, slicer.vtkMRMLNode):
                    node = nodeOrId
                else:
                    node = slicer.mrmlScene.GetNodeByID(nodeOrId)
            except Exception:
                node = None

            if not node:
                slicer.util.warningDisplay("Could not find the generated script node to open in Script Editor.")
                return False

            # Switch module
            slicer.util.selectModule('ScriptEditor')

            attempts = {"count": 0}
            max_attempts = 30  # ~3s with 100ms interval

            def trySetNode():
                attempts["count"] += 1
                try:
                    w = slicer.modules.scripteditor.widgetRepresentation()
                    if not w:
                        raise RuntimeError("ScriptEditor widget not ready")
                    pyw = w.self() if hasattr(w, 'self') else w
                    if hasattr(pyw, 'setCurrentNode'):
                        pyw.setCurrentNode(node)
                        return  # success
                    # Fallback to combobox if accessible
                    combo = slicer.util.findChild(w, 'nodeComboBox')
                    if combo:
                        combo.setCurrentNode(node)
                        return  # success
                    raise RuntimeError("No setter for current node yet")
                except Exception:
                    if attempts["count"] < max_attempts:
                        qt.QTimer.singleShot(100, trySetNode)
                    else:
                        slicer.util.warningDisplay("Opened Script Editor, but couldn’t auto-select the script. Please choose it from the dropdown.")
            qt.QTimer.singleShot(0, trySetNode)
            return True
        except Exception:
            return False

    def diagnostic_print(self, message, error=False):
        """Print diagnostic message to both log and UI"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {'❌ ' if error else ''}" + message
        print(formatted_msg)  # Console output
        logging.info(formatted_msg)  # Log file
        if self._outputCallback:
            self._outputCallback(formatted_msg)  # UI output
        slicer.app.processEvents()
    
    def _notifyNodeContentChanged(self, textNode):
        """Notify that a text node's content has changed to update UI displays"""
        # Trigger a Modified event to update any observers (like Monaco editor)
        textNode.Modified()

    def processRequest(self, apiKey, userPrompt, scriptName=None, outputPath=None):
        try:
            from openai import OpenAI
            
            # Get selected model
            model_name = self.getModel()
            
            # Jetstream2 model endpoints (free, no API key required)
            jetstream_endpoints = {
                "DeepSeek-R1": "https://llm.jetstream-cloud.org/sglang/v1",
                "gpt-oss-120b": "https://llm.jetstream-cloud.org/gpt-oss-120b/v1",
                "llama-4-scout": "https://llm.jetstream-cloud.org/llama-4-scout/v1",
            }
            
            # Create appropriate client based on model
            if model_name in jetstream_endpoints:
                # Jetstream2 models - no API key needed, access from Jetstream2 network
                client = OpenAI(
                    api_key="empty",  # Jetstream2 doesn't require authentication from their network
                    base_url=jetstream_endpoints[model_name]
                )
            else:
                # GitHub Models API (included with GitHub Copilot subscription)
                client = OpenAI(
                    api_key=apiKey,
                    base_url="https://models.inference.ai.azure.com"
                )
        except ImportError:
            return {"success": False, "error": "OpenAI library not found. Please install it with: pip install openai"}
        except Exception as e:
            return {"success": False, "error": f"Failed to initialize AI client: {str(e)}"}
        return {"success": False, "error": "No script name specified."}

    def processRequestToNode(self, apiKey, userPrompt, textNode, outputPath=None, existingCode=None):
        """Process request and write generated code directly to a text node"""
        try:
            from openai import OpenAI
            
            # Get selected model
            model_name = self.getModel()
            
            # Jetstream2 model endpoints (free, no API key required)
            jetstream_endpoints = {
                "DeepSeek-R1": "https://llm.jetstream-cloud.org/sglang/v1",
                "gpt-oss-120b": "https://llm.jetstream-cloud.org/gpt-oss-120b/v1",
                "llama-4-scout": "https://llm.jetstream-cloud.org/llama-4-scout/v1",
            }
            
            # Create appropriate client based on model
            if model_name in jetstream_endpoints:
                client = OpenAI(
                    api_key="empty",
                    base_url=jetstream_endpoints[model_name]
                )
            else:
                client = OpenAI(
                    api_key=apiKey,
                    base_url="https://models.inference.ai.azure.com"
                )
        except ImportError:
            return {"success": False, "error": "OpenAI library not found. Please install it with: pip install openai"}
        except Exception as e:
            return {"success": False, "error": f"Failed to initialize AI client: {str(e)}"}
        
        if not textNode:
            return {"success": False, "error": "No text node provided."}
        
        scriptName = textNode.GetName().replace('.py', '')
        
        # Generate code using AI
        return self.createScriptToNode(client, userPrompt, textNode, scriptName, outputPath, existingCode)







    def createScriptToNode(self, client, userPrompt, textNode, scriptName, outputPath=None, existingCode=None):
        """Create a Python script and write it directly to a text node"""
        import traceback
        
        max_debug_attempts = self.getDebugIterations()
        current_code = existingCode  # Start with existing code if provided
        error_history = ""
        
        for attempt in range(max_debug_attempts + 1):
            try:
                if attempt == 0:
                    if existingCode:
                        # Improvement/fix mode
                        prompt_for_creation = (
                            f"Improve or fix the following Python script for 3D Slicer based on this feedback: {userPrompt}\\n"
                            f"The script should continue to be compatible with 3D Slicer's Python console. "
                            f"Use only modern, non-deprecated Slicer API calls. "
                            f"Include proper error handling and user feedback using slicer.util functions. "
                            f"Return ONLY the complete improved Python code without any explanation or markdown formatting.")
                    else:
                        # New script generation mode
                        prompt_for_creation = (
                            f"Create a complete Python script named '{scriptName}' that implements the following functionality: {userPrompt}. "
                            f"The script should be designed to run in 3D Slicer's Python console. Use only modern, non-deprecated Slicer API calls. "
                            f"Include proper error handling and user feedback using slicer.util functions. "
                            f"Return ONLY the complete Python code without any explanation or markdown formatting.")
                else:
                    prompt_for_creation = (
                        f"Debug and fix the Python script for 3D Slicer. The script should implement: {userPrompt}\\n"
                        f"Use only modern, non-deprecated Slicer API calls. Current error (Debug Attempt {attempt}/{max_debug_attempts}):\\n{error_history}")

                # Get script template for context (only if no existing code)
                script_template = existingCode or self.get_script_template(scriptName)
                new_code = self.call_ai(client, prompt_for_creation, current_code or script_template, error_history, "script")
                
                if new_code is None:
                    return {"success": False, "error": "AI API call failed. Check the conversation log for details."}

                # ALWAYS write the code to the text node first (so it shows in editor even if execution fails)
                textNode.SetText(new_code)
                current_code = new_code
                
                # Trigger editor update - this ensures Monaco editor displays the generated code
                self._notifyNodeContentChanged(textNode)
                
                # Optionally save to file if output path provided
                if outputPath:
                    scripts_dir = os.path.join(outputPath, "Scripts")
                    if not os.path.exists(scripts_dir):
                        os.makedirs(scripts_dir)
                    script_file_path = os.path.join(scripts_dir, f"{scriptName}.py")
                    self.write_code(script_file_path, new_code)
                    
                    # Link storage node
                    storageNode = textNode.GetStorageNode()
                    if not storageNode:
                        storageNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextStorageNode')
                        textNode.SetAndObserveStorageNodeID(storageNode.GetID())
                    storageNode.SetFileName(script_file_path)
                
                # Test the script
                self.diagnostic_print(f"Attempt {attempt + 1}: Validating script syntax...")
                try:
                    compile(new_code, f"<{scriptName}>", 'exec')
                except SyntaxError as e:
                    raise RuntimeError(f"Syntax error in generated script: {str(e)}")

                self.diagnostic_print(f"Attempt {attempt + 1}: Testing script execution...")
                test_success, test_error = self.testScriptExecution(new_code, scriptName)
                if not test_success:
                    raise RuntimeError(f"Script execution test failed: {test_error}")
                
                # Execute in Slicer
                self.diagnostic_print(f"Attempt {attempt + 1}: Executing script in Slicer...")
                exec_success, exec_error = self.executeScriptInSlicer(new_code, scriptName)
                if not exec_success:
                    self.diagnostic_print(f"Script execution in Slicer failed: {exec_error}")
                    raise RuntimeError(f"Script runtime execution failed: {exec_error}")
                
                # Success!
                result_message = f"Script '{scriptName}' generated successfully"
                if attempt > 0:
                    result_message += f" after {attempt} debug attempts"
                result_message += ". Code written to node and ready to execute."
                
                return {"success": True, "message": result_message}

            except Exception as e:
                error_msg = f"Error on attempt {attempt + 1}:\\n{str(e)}\\n{traceback.format_exc()}"
                self.diagnostic_print(f"Script generation failed:\\n{error_msg}", error=True)
                
                formatted_error = f"""
ATTEMPT {attempt + 1} FAILED:
Error Type: {type(e).__name__}
Error Message: {str(e)}

Generated Code That Failed:
{new_code if 'new_code' in locals() else 'No code generated'}

Full Traceback:
{traceback.format_exc()}
"""
                error_history = formatted_error
                
                if attempt == max_debug_attempts:
                    return {"success": False, "error": f"Failed to create script after {max_debug_attempts} debug attempts. Final error: {str(e)}\\n\\nError History:\\n{error_history}"}

    def createSimpleScript(self, client, userPrompt, scriptName, outputPath=None):
        """Create a simple Python script that can be executed in Slicer's Python console"""
        import traceback
        
        if outputPath:
            # Use custom output path with Scripts/ScriptName.py structure
            scripts_dir = os.path.join(outputPath, "Scripts")
            script_file_path = os.path.join(scripts_dir, f"{scriptName}.py")
        else:
            # Fallback to default directory
            settings_dir = os.path.dirname(slicer.app.slicerUserSettingsFilePath)
            scripts_dir = os.path.join(settings_dir, "DeveloperAgent-Scripts")
            script_file_path = os.path.join(scripts_dir, f"{scriptName}.py")
        
        # Create scripts directory if it doesn't exist
        if not os.path.exists(scripts_dir):
            os.makedirs(scripts_dir)
        
        max_debug_attempts = self.getDebugIterations()
        current_code = None
        error_history = ""
        
        for attempt in range(max_debug_attempts + 1):
            try:
                if attempt == 0:
                    prompt_for_creation = (
                        f"Create a complete Python script named '{scriptName}' that implements the following functionality: {userPrompt}. "
                        f"The script should be designed to run in 3D Slicer's Python console. Use only modern, non-deprecated Slicer API calls. "
                        f"Include proper error handling and user feedback using slicer.util functions. "
                        f"Return ONLY the complete Python code without any explanation or markdown formatting.")
                else:
                    prompt_for_creation = (
                        f"Debug and fix the Python script for 3D Slicer. The script should implement: {userPrompt}\n"
                        f"Use only modern, non-deprecated Slicer API calls. Current error (Debug Attempt {attempt}/{max_debug_attempts}):\n{error_history}")

                # Get script template for context
                script_template = self.get_script_template(scriptName)
                new_code = self.call_ai(client, prompt_for_creation, current_code or script_template, error_history, "script")
                
                if new_code is None:
                    return {"success": False, "error": "AI API call failed. Check the conversation log for details. This may be due to rate limits, invalid API key, or network issues."}

                # Write the script to file
                self.write_code(script_file_path, new_code)
                current_code = new_code
                
                # Verify the file was written correctly
                if not os.path.exists(script_file_path):
                    raise RuntimeError(f"Failed to create script file at: {script_file_path}")
                
                # Load the script file as a text node after verifying file exists
                # Only create text node after ALL attempts are done (success or failure)
                # Don't create it here on every attempt - it will cause duplicates
                
                # Verify file content
                try:
                    with open(script_file_path, 'r', encoding='utf-8') as f:
                        written_content = f.read()
                    if not written_content.strip():
                        raise RuntimeError("Script file was created but is empty")
                    self.diagnostic_print(f"Script file created successfully: {len(written_content)} characters")
                except Exception as e:
                    raise RuntimeError(f"Cannot read back written script file: {str(e)}")

                # Test the script by attempting to compile it
                self.diagnostic_print(f"Attempt {attempt + 1}: Validating script syntax...")
                try:
                    compile(new_code, script_file_path, 'exec')
                except SyntaxError as e:
                    raise RuntimeError(f"Syntax error in generated script: {str(e)}")

                # Try to execute the script in a controlled environment to check for basic errors
                self.diagnostic_print(f"Attempt {attempt + 1}: Testing script execution...")
                test_success, test_error = self.testScriptExecution(new_code, scriptName)
                if not test_success:
                    # Log the actual generated code for debugging
                    self.diagnostic_print(f"Generated code that failed (first 800 chars):")
                    self.diagnostic_print(f"---START CODE---")
                    self.diagnostic_print(new_code[:800])
                    if len(new_code) > 800:
                        self.diagnostic_print("...CODE TRUNCATED...")
                    self.diagnostic_print(f"---END CODE---")
                    raise RuntimeError(f"Script execution test failed: {test_error}")
                
                # Now execute the actual script in Slicer's Python console to catch runtime errors
                self.diagnostic_print(f"Attempt {attempt + 1}: Executing script in Slicer Python console...")
                exec_success, exec_error = self.executeScriptInSlicer(new_code, scriptName)
                if not exec_success:
                    self.diagnostic_print(f"Script execution in Slicer failed: {exec_error}")
                    raise RuntimeError(f"Script runtime execution failed: {exec_error}")
                
                # If we get here, script was created and tested successfully
                result_message = f"Script '{scriptName}' created and tested successfully"
                if attempt > 0:
                    result_message += f" after {attempt} debug attempts"
                
                if outputPath:
                    result_message += f".\n\nScript structure created:\n📁 {outputPath}/\n  └── 📁 Scripts/\n      └── 📄 {scriptName}.py"
                else:
                    result_message += f". Saved to: {script_file_path}"
                
                # Load script as text node on success (no UI switch)
                node, load_msg = self.loadScriptIntoScene(script_file_path)
                if node:
                    self.diagnostic_print(f"Script loaded as text node: {node.GetName()} ({load_msg})")
                    # Remember for quick open
                    self.lastScriptNodeID = node.GetID()
                    self.lastScriptFilePath = script_file_path
                else:
                    self.diagnostic_print(f"Could not load script as text node: {load_msg}")
                
                # Script created and tested successfully
                return {"success": True, "message": result_message}

            except Exception as e:
                error_msg = f"Error on attempt {attempt + 1}:\n{str(e)}\n{traceback.format_exc()}"
                self.diagnostic_print(f"Script creation failed:\n{error_msg}", error=True)
                
                # Format error for AI to understand and fix
                formatted_error = f"""
ATTEMPT {attempt + 1} FAILED:
Error Type: {type(e).__name__}
Error Message: {str(e)}

Generated Code That Failed:
{new_code if 'new_code' in locals() else 'No code generated'}

Full Traceback:
{traceback.format_exc()}

DEBUGGING GUIDANCE:
- Analyze the error message carefully to understand what went wrong
- If Python suggests an alternative (e.g., "Did you mean: X?"), use that suggestion
- Search the Script Repository (https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html) for working examples of similar functionality
- If the same error occurs after multiple attempts, try a fundamentally different approach
- Consider using simpler, higher-level helper functions instead of low-level APIs
"""
                error_history = formatted_error
                
                if attempt == max_debug_attempts:
                    # Last attempt failed - still try to create text node for manual fixing
                    if os.path.exists(script_file_path):
                        node, load_msg = self.loadScriptIntoScene(script_file_path)
                        if node:
                            self.diagnostic_print(f"Script loaded as text node for manual review: {node.GetName()} ({load_msg})")
                            # Remember for quick open
                            self.lastScriptNodeID = node.GetID()
                            self.lastScriptFilePath = script_file_path
                        else:
                            self.diagnostic_print(f"Could not load script as text node: {load_msg}")
                    
                    return {"success": False, "error": f"Failed to create script after {max_debug_attempts} debug attempts. Final error: {str(e)}\n\nError History:\n{error_history}"}

    def get_script_template(self, scriptName):
        """Get a basic template for a Slicer Python script"""
        return f'''"""
{scriptName} - Generated by DeveloperAgent
This script implements custom functionality for 3D Slicer
"""

import slicer
import slicer.util
import logging

# Your implementation goes here
print("Script executed successfully!")
'''

    def testScriptExecution(self, script_code, script_name):
        """Test script execution in a safe environment - but don't actually execute, just validate"""
        try:
            self.diagnostic_print(f"Testing script '{script_name}' for syntax validation...")
            
            # Only compile to check syntax - don't execute yet
            compiled_code = compile(script_code, f"<script_{script_name}>", 'exec')
            
            self.diagnostic_print("  ✓ Script syntax validation completed successfully")
            return True, ""
            
        except Exception as e:
            import traceback
            error_msg = f"{script_name} syntax validation failed: {str(e)}"
            self.diagnostic_print(f"[Python] {error_msg}")
            self.diagnostic_print(f"[Python] Traceback (most recent call last):")
            # Get the traceback and format it properly
            tb_lines = traceback.format_exc().strip().split('\n')
            for line in tb_lines[1:]:  # Skip the first line as it's redundant
                self.diagnostic_print(f"[Python] {line}")
            self.diagnostic_print("  ❌ Script syntax validation FAILED")
            return False, error_msg

    def executeScriptInSlicer(self, script_code, script_name):
        """Execute the script in Slicer's actual Python console and capture any runtime errors"""
        try:
            self.diagnostic_print(f"Executing '{script_name}' in Slicer Python console...")
            
            # Clear the scene before execution to ensure clean state
            
            # Execute the script directly and let errors propagate
            try:
                # Execute the script as-is - no mocking, let it fail naturally
                exec(script_code, {'slicer': slicer, 'logging': logging, 'SampleData': __import__('SampleData'), '__name__': '__main__'})
                
                # If we get here, no exception was raised
                self.diagnostic_print("  ✓ Script executed successfully in Slicer")
                return True, ""
                    
            except Exception as exec_exception:
                import traceback
                import sys
                # Direct execution exception - this is a real runtime error
                execution_error = str(exec_exception)
                full_traceback = traceback.format_exc()
                
                # Get detailed exception info for better debugging
                exc_type, exc_value, exc_tb = sys.exc_info()
                error_details = {
                    'type': exc_type.__name__ if exc_type else 'Unknown',
                    'message': str(exc_value) if exc_value else str(exec_exception),
                    'repr': repr(exc_value) if exc_value else repr(exec_exception)
                }
                
                # Try to get more info about the error
                enhanced_error = execution_error
                if hasattr(exc_value, 'args') and exc_value.args:
                    enhanced_error = f"{execution_error} (args: {exc_value.args})"
                
                self.diagnostic_print(f"Script execution FAILED with exception: {enhanced_error}")
                self.diagnostic_print(f"Exception type: {error_details['type']}, repr: {error_details['repr']}")
                self.diagnostic_print(f"Full traceback: {full_traceback}")
                self.diagnostic_print("  ❌ Script execution FAILED in Slicer")
                
                return False, f"Script execution failed: {execution_error}\n\nFull traceback:\n{full_traceback}"
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to execute script in Slicer: {str(e)}"
            full_traceback = traceback.format_exc()
            
            self.diagnostic_print(f"[Slicer Execution Error] {error_msg}")
            self.diagnostic_print(f"[Slicer Execution Error] Full traceback:")
            for line in full_traceback.strip().split('\n'):
                self.diagnostic_print(f"[Slicer Execution Error] {line}")
            
            return False, f"{error_msg}\n{full_traceback}"

    def openInScriptEditor(self, script_file_path):
        """Try to open the script file in the Script Editor extension using its file reader"""
        try:
            # First, verify the file exists and is readable
            if not os.path.exists(script_file_path):
                return {"success": False, "error": f"Script file does not exist: {script_file_path}"}
            
            # Check if Script Editor extension is available
            if not hasattr(slicer.modules, 'scripteditor'):
                return {"success": False, "error": "Script Editor extension is not installed or available"}
            
            self.diagnostic_print(f"Loading script file using Script Editor's file reader: {script_file_path}")
            
            try:
                # Use slicer.util.loadText which will use Script Editor's custom file reader
                # This handles all the proper node configuration automatically
                success = slicer.util.loadText(script_file_path)
                
                if success:
                    self.diagnostic_print("✓ Script loaded successfully using Script Editor's file reader")
                    
                    # Find and select the loaded node in Script Editor
                    slicer.util.selectModule('ScriptEditor')
                    slicer.app.processEvents()
                    
                    # Find the node that was just loaded
                    loadedNodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLTextNode")
                    for i in range(loadedNodes.GetNumberOfItems()):
                        node = loadedNodes.GetItemAsObject(i)
                        if node.GetAttribute("mimetype") == "text/x-python":
                            storageNode = node.GetStorageNode()
                            if storageNode and storageNode.GetFileName() == script_file_path:
                                # Get Script Editor widget and set current node
                                script_editor_widget = slicer.modules.scripteditor.widgetRepresentation()
                                if script_editor_widget:
                                    widget_self = script_editor_widget.self() if hasattr(script_editor_widget, 'self') else script_editor_widget
                                    if hasattr(widget_self, 'setCurrentNode'):
                                        widget_self.setCurrentNode(node)
                                    elif hasattr(widget_self, 'nodeComboBox'):
                                        widget_self.nodeComboBox.setCurrentNode(node)
                                    self.diagnostic_print(f"✓ Selected loaded script in Script Editor: {node.GetName()}")
                                break
                    
                    loadedNodes.UnRegister(None)
                    return {"success": True, "message": f"Script loaded and opened in Script Editor"}
                else:
                    return {"success": False, "error": "Script Editor file reader failed to load the file"}
                    
            except Exception as e:
                self.diagnostic_print(f"Failed to load using slicer.util.loadText: {e}")
                return {"success": False, "error": f"Failed to load script: {str(e)}"}
            
        except Exception as e:
            error_msg = f"Failed to open script in Script Editor: {str(e)}"
            self.diagnostic_print(f"❌ {error_msg}", error=True)
            return {"success": False, "error": error_msg}

    def debugScriptEditor(self):
        """Debug method to inspect Script Editor widget structure"""
        try:
            if not hasattr(slicer.modules, 'scripteditor'):
                self.diagnostic_print("Script Editor not available")
                return
            
            slicer.util.selectModule('ScriptEditor')
            slicer.app.processEvents()
            qt.QThread.msleep(1000)
            
            widget = slicer.modules.scripteditor.widgetRepresentation()
            if not widget:
                self.diagnostic_print("No widget representation")
                return
            
            widget_self = widget.self() if hasattr(widget, 'self') else widget
            
            self.diagnostic_print("=== Script Editor Widget Debug Info ===")
            self.diagnostic_print(f"Widget type: {type(widget_self)}")
            
            # List all methods and properties
            all_attrs = [attr for attr in dir(widget_self) if not attr.startswith('_')]
            file_related = [attr for attr in all_attrs if any(keyword in attr.lower() for keyword in ['file', 'script', 'load', 'open', 'save', 'text', 'editor'])]
            
            self.diagnostic_print(f"File-related attributes: {file_related}")
            
            # Check for text editors
            text_editors = []
            for attr in all_attrs:
                try:
                    obj = getattr(widget_self, attr)
                    if hasattr(obj, 'setPlainText'):
                        text_editors.append(f"{attr} ({type(obj)})")
                except:
                    continue
            
            self.diagnostic_print(f"Text editor attributes: {text_editors}")
            
            # Check children only if findChildren method exists
            if hasattr(widget_self, 'findChildren'):
                try:
                    plain_text_edits = widget_self.findChildren(qt.QPlainTextEdit)
                    text_edits = widget_self.findChildren(qt.QTextEdit)
                    
                    self.diagnostic_print(f"QPlainTextEdit children: {len(plain_text_edits)}")
                    self.diagnostic_print(f"QTextEdit children: {len(text_edits)}")
                except Exception as e:
                    self.diagnostic_print(f"findChildren call failed: {e}")
            else:
                self.diagnostic_print("Widget does not have findChildren method")
            
        except Exception as e:
            self.diagnostic_print(f"Debug failed: {e}")



    def read_code(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except: return None

    def write_code(self, file_path, new_code):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_code)
        except: pass

    def call_ai(self, client, prompt, code_context, error_history, request_type="script"):
        
        # DIAGNOSTIC: Log what we're sending to the AI
        self.diagnostic_print("=" * 80)
        self.diagnostic_print("AI CALL DIAGNOSTIC")
        self.diagnostic_print(f"Request Type: {request_type}")
        self.diagnostic_print(f"Prompt (first 200 chars): {prompt[:200]}...")
        self.diagnostic_print(f"Code Context Length: {len(code_context)} chars")
        self.diagnostic_print(f"Error History Length: {len(error_history)} chars")
        if error_history:
            self.diagnostic_print(f"Error History (first 500 chars): {error_history[:500]}...")
        
        # Load prompt configuration with user request for RAG retrieval
        prompts = self._get_prompts(user_request=prompt)
        self.diagnostic_print(f"Using prompt version: {prompts['version']}")
        self.diagnostic_print(f"Prompt source: {'custom' if PROMPTS_LOADED else 'built-in'}")
        self.diagnostic_print("=" * 80)
        
        # Build system prompt from configuration
        system_prompt = prompts['base'] + prompts['script_requirements']
        
        # Build user prompt with error section if needed
        error_section = ""
        if error_history:
            error_section = prompts['error_section'].format(error_history=error_history)
        
        user_prompt = prompts['user_template'].format(
            prompt=prompt,
            error_section=error_section,
            code_context=code_context
        )

        try:
            # DIAGNOSTIC: Log the full user prompt being sent
            self.diagnostic_print(f"SENDING TO AI - Full message length: {len(user_prompt)} chars")
            
            # Get the model from settings
            model_name = self.getModel()
            self.diagnostic_print(f"Using AI model: {model_name}")
            
            # Get AI parameters from configuration
            ai_params = prompts['ai_params']
            
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=ai_params.get('temperature', 0.3),
                max_tokens=ai_params.get('max_tokens', 8000)
            )
            
            generated_code = response.choices[0].message.content.strip()
            self.diagnostic_print(f"RECEIVED FROM AI - Code length: {len(generated_code)} chars")
            
            # Strip <think> tags from DeepSeek-R1 responses
            import re
            # Remove everything between <think> and </think> tags (including the tags)
            generated_code = re.sub(r'<think>.*?</think>', '', generated_code, flags=re.DOTALL)
            # Also handle <Think> tags (case insensitive)
            generated_code = re.sub(r'<Think>.*?</Think>', '', generated_code, flags=re.DOTALL|re.IGNORECASE)
            generated_code = generated_code.strip()
            
            # Clean up the response
            if generated_code.startswith("```python"):
                # Extract code from markdown code block
                code = generated_code[generated_code.find("```python")+9:]
                code = code[:code.rfind("```")].strip()
            elif generated_code.startswith("```"):
                # Handle generic code blocks
                code = generated_code[generated_code.find("```")+3:]
                code = code[:code.rfind("```")].strip()
            else:
                code = generated_code
            
            # Remove leading explanation comments but keep functional comments
            code_lines = code.split('\n')
            while code_lines and code_lines[0].strip().startswith('#') and any(word in code_lines[0].lower() for word in ['here', 'this', 'implementation', 'solution']):
                code_lines.pop(0)
            
            final_code = '\n'.join(code_lines).strip()
            
            # Fallback to template if no valid code generated
            if not final_code or len(final_code.strip()) < 50:
                final_code = code_context
            
            # Validate the generated code
            validation_issues = self.validateSlicerCode(final_code)
            if validation_issues:
                self.diagnostic_print(f"Code validation warnings: {'; '.join(validation_issues[:3])}", error=True)
            
            return final_code
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            
            # Check for rate limit errors
            if "RateLimitError" in str(type(e).__name__) or "429" in error_msg or "rate limit" in error_msg.lower():
                # Extract wait time if available
                wait_time = "unknown"
                if "wait" in error_msg.lower():
                    import re
                    wait_match = re.search(r'wait (\d+) seconds', error_msg)
                    if wait_match:
                        seconds = int(wait_match.group(1))
                        hours = seconds // 3600
                        minutes = (seconds % 3600) // 60
                        wait_time = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                
                self.diagnostic_print("❌ RATE LIMIT ERROR DETECTED", error=True)
                self.diagnostic_print(f"You have exceeded your API quota. Wait time: {wait_time}", error=True)
                self.diagnostic_print(f"Full error: {error_msg}", error=True)
                return None  # Return None to signal failure
            
            # Check for authentication errors
            elif "401" in error_msg or "authentication" in error_msg.lower() or "invalid" in error_msg.lower():
                self.diagnostic_print("❌ AUTHENTICATION ERROR", error=True)
                self.diagnostic_print("Your GitHub token may be invalid or expired.", error=True)
                self.diagnostic_print(f"Full error: {error_msg}", error=True)
                return None
            
            # Other API errors
            else:
                logging.error(f"OpenAI API call failed: {e}", exc_info=True)
                self.diagnostic_print(f"❌ AI API call failed: {error_msg}", error=True)
                self.diagnostic_print(f"Traceback: {traceback.format_exc()}", error=True)
                return None  # Return None instead of template

    def validateSlicerCode(self, code):
        """Validate generated code against known Slicer API patterns and common mistakes"""
        issues = []
        
        # Check for missing essential imports
        if "import slicer" not in code:
            issues.append("Missing essential import: import slicer")
        
        # Check for SampleData usage without import
        if "SampleData." in code and "import SampleData" not in code:
            issues.append("Using SampleData without import - add 'import SampleData'")
        
        # Check for common mistake: forgetting [0] on SampleData.downloadFromURL
        if "SampleData.downloadFromURL(" in code and "downloadFromURL(urls=" in code:
            # Check if followed by [0] within reasonable distance
            import re
            pattern = r'SampleData\.downloadFromURL\([^)]+\)(?!\[0\])'
            matches = re.findall(pattern, code)
            if matches:
                issues.append("CRITICAL: SampleData.downloadFromURL returns a LIST - must use [0] to get first element")
        
        # Check for node operations without None checks
        if ".GetName()" in code or ".GetID()" in code or ".SetName(" in code:
            if "if" not in code and "is None" not in code:
                issues.append("WARNING: Node operations without None checks may fail")
        
        # Check for lowercase VTK method names (common mistake)
        vtk_method_patterns = ['.getname(', '.setname(', '.getid(', '.setvisibility(']
        for pattern in vtk_method_patterns:
            if pattern in code.lower() and pattern in code:
                issues.append(f"ERROR: VTK uses CapitalCase methods - found lowercase '{pattern}'")
        
        # Check for invalid layout constants
        if "setLayout(0)" in code or "setLayout(1)" in code:
            issues.append("WARNING: Use named layout constants like slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView")
        
        # Check for basic Python syntax issues
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            issues.append(f"SYNTAX ERROR: {str(e)}")
        
        return issues



#
# DeveloperAgentWidget
#
class DeveloperAgentWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = DeveloperAgentLogic()
        self.logic.setOutputCallback(self.appendToConversationView)
        self._parameterNode = None
        self._currentObservedNode = None
        self._nodeModifiedTag = None
        self._isSyncing = False

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.layout.setContentsMargins(15, 15, 15, 15)

        # --- API Configuration ---
        setupCollapsibleButton = ctk.ctkCollapsibleButton()
        setupCollapsibleButton.text = "API Configuration"
        self.layout.addWidget(setupCollapsibleButton)
        setupFormLayout = qt.QFormLayout(setupCollapsibleButton)
        self.apiKeyLineEdit = qt.QLineEdit()
        # --- GitHub Token Setup ---
        self.apiKeyLineEdit.setPlaceholderText("ghp_... or ghu_... (GitHub Personal Access Token)")
        # To get your token: https://github.com/settings/tokens
        setupFormLayout.addRow("GitHub Token:", self.apiKeyLineEdit)
        
        # --- Debug Iterations Configuration ---
        self.debugIterationsSpinBox = qt.QSpinBox()
        self.debugIterationsSpinBox.setMinimum(0)
        self.debugIterationsSpinBox.setMaximum(10)
        self.debugIterationsSpinBox.setValue(0)
        self.debugIterationsSpinBox.setToolTip("Number of debug attempts when code generation fails (default: 0)")
        setupFormLayout.addRow("Debug Iterations:", self.debugIterationsSpinBox)
        
        # --- Model Selection ---
        self.modelSelector = qt.QComboBox()
        # Load models from configuration
        prompts = self.logic._get_prompts()
        available_models = prompts.get('available_models', [("DeepSeek-R1", "DeepSeek-R1")])
        default_model = prompts.get('default_model', 'DeepSeek-R1')
        
        # Populate model selector
        default_index = 0
        for i, (display_name, model_id) in enumerate(available_models):
            self.modelSelector.addItem(display_name, model_id)
            if model_id == default_model:
                default_index = i
        
        self.modelSelector.setCurrentIndex(default_index)
        self.modelSelector.setToolTip("Select the AI model to use for code generation. Different models have different rate limits and capabilities.\nUpdate models in Resources/prompts_config.py")
        setupFormLayout.addRow("AI Model:", self.modelSelector)
        
        # --- Output Path Configuration ---
        outputPathLayout = qt.QHBoxLayout()
        self.outputPathLineEdit = qt.QLineEdit()
        self.outputPathLineEdit.setPlaceholderText("Click Browse to select output directory...")
        # Restore saved output path from settings
        settings = qt.QSettings()
        saved_path = settings.value("DeveloperAgent/outputPath", "")
        if saved_path:
            self.outputPathLineEdit.setText(saved_path)
        self.browseOutputPathButton = qt.QPushButton("Browse...")
        self.browseOutputPathButton.clicked.connect(self.onBrowseOutputPath)
        outputPathLayout.addWidget(self.outputPathLineEdit)
        outputPathLayout.addWidget(self.browseOutputPathButton)
        setupFormLayout.addRow("Output Directory:", outputPathLayout)

        # --- Script Development ---
        devCollapsibleButton = ctk.ctkCollapsibleButton()
        devCollapsibleButton.text = "Script Development"
        devCollapsibleButton.collapsed = False
        self.layout.addWidget(devCollapsibleButton)
        devFormLayout = qt.QFormLayout(devCollapsibleButton)

        # Add GitHub token help
        github_token_info = qt.QLabel("🔑 GitHub Token: Optional for DeepSeek-R1 (Jetstream2), required for GitHub models")
        github_token_info.setStyleSheet("color: #0366d6; font-size: 10px;")
        github_token_info.setWordWrap(True)
        devFormLayout.addRow(github_token_info)
        
        # --- Conversation UI & Prompt (before editor) ---
        devFormLayout.addRow(qt.QLabel("<b>Conversation & Prompt</b>"))
        
        # Initialize conversation view first (needed for error messages)
        self.conversationView = qt.QTextBrowser()
        self.conversationView.setMinimumHeight(200)
        devFormLayout.addRow(self.conversationView)
        
        # Check for required libraries and extensions
        self.checkForOpenAILibrary()
        self.checkForScriptEditor()
        
        self.promptTextEdit = qt.QTextEdit()
        self.promptTextEdit.setPlaceholderText("Describe what you want the script to do, or provide feedback about the current code...")
        self.promptTextEdit.setFixedHeight(100)
        devFormLayout.addRow(self.promptTextEdit)
        
        # Add checkbox to include current code as context
        self.includeCurrentCodeCheckbox = qt.QCheckBox("Include current code as context (for improvements/fixes)")
        self.includeCurrentCodeCheckbox.setChecked(False)
        self.includeCurrentCodeCheckbox.setToolTip(
            "When checked, sends the current editor code to AI for improvement/debugging.\n"
            "Use this to:\n"
            "  • Fix errors in generated code\n"
            "  • Add features to existing scripts\n"
            "  • Refine or optimize current implementation\n\n"
            "When unchecked, AI generates new code from scratch."
        )
        devFormLayout.addRow(self.includeCurrentCodeCheckbox)
        
        self.sendButton = qt.QPushButton("🚀 Send to Agent")
        devFormLayout.addRow(self.sendButton)
        
        # --- Script Editor (after prompt) ---
        devFormLayout.addRow(qt.QLabel("<b>Script Editor</b>"))
        
        # Create container for editor components
        editorContainer = qt.QWidget()
        editorLayout = qt.QVBoxLayout(editorContainer)
        editorLayout.setContentsMargins(0, 0, 0, 0)
        
        # Add editor settings (theme and font size)
        settingsLayout = qt.QHBoxLayout()
        
        # Theme selector
        themeLabel = qt.QLabel("Theme:")
        self.lightThemeRadio = qt.QRadioButton("Light")
        self.darkThemeRadio = qt.QRadioButton("Dark")
        self.lightThemeRadio.setChecked(True)  # Default to light theme
        self.lightThemeRadio.toggled.connect(self.onThemeChanged)
        self.darkThemeRadio.toggled.connect(self.onThemeChanged)
        
        # Font size slider
        fontSizeLabel = qt.QLabel("Font Size:")
        self.fontSizeSlider = qt.QSlider(qt.Qt.Horizontal)
        self.fontSizeSlider.setMinimum(8)
        self.fontSizeSlider.setMaximum(32)
        self.fontSizeSlider.setValue(14)
        self.fontSizeSlider.setTickPosition(qt.QSlider.TicksBelow)
        self.fontSizeSlider.setTickInterval(4)
        self.fontSizeSlider.setMaximumWidth(150)
        self.fontSizeSlider.valueChanged.connect(self.onFontSizeChanged)
        
        self.fontSizeValueLabel = qt.QLabel("14")
        self.fontSizeValueLabel.setMinimumWidth(25)
        
        settingsLayout.addWidget(themeLabel)
        settingsLayout.addWidget(self.lightThemeRadio)
        settingsLayout.addWidget(self.darkThemeRadio)
        settingsLayout.addWidget(qt.QLabel("  |  "))
        settingsLayout.addWidget(fontSizeLabel)
        settingsLayout.addWidget(self.fontSizeSlider)
        settingsLayout.addWidget(self.fontSizeValueLabel)
        settingsLayout.addStretch()
        
        settingsWidget = qt.QWidget()
        settingsWidget.setLayout(settingsLayout)
        editorLayout.addWidget(settingsWidget)
        
        # Add node selector
        nodeSelectorLayout = qt.QHBoxLayout()
        nodeSelectorLabel = qt.QLabel("Script:")
        self.scriptNodeSelector = slicer.qMRMLNodeComboBox()
        self.scriptNodeSelector.nodeTypes = ["vtkMRMLTextNode"]
        self.scriptNodeSelector.addAttribute("vtkMRMLTextNode", "mimetype", "text/x-python")
        self.scriptNodeSelector.showChildNodeTypes = False
        self.scriptNodeSelector.showHidden = False
        self.scriptNodeSelector.selectNodeUponCreation = True
        self.scriptNodeSelector.noneEnabled = True
        self.scriptNodeSelector.removeEnabled = True
        self.scriptNodeSelector.renameEnabled = True
        self.scriptNodeSelector.addEnabled = True
        self.scriptNodeSelector.baseName = "Script"
        self.scriptNodeSelector.noneDisplay = "(Create New Python Script)"
        self.scriptNodeSelector.setMRMLScene(slicer.mrmlScene)
        self.scriptNodeSelector.setToolTip("Select or create a script node")
        
        nodeSelectorLayout.addWidget(nodeSelectorLabel)
        nodeSelectorLayout.addWidget(self.scriptNodeSelector)
        editorLayout.addLayout(nodeSelectorLayout)
        
        # LAZY INITIALIZATION: Don't create Monaco editor during setup to avoid conflicts
        # It will be created on first enter() when user actually visits the module
        self.codeEditor = None
        self.editorInitialized = False
        
        # Create placeholder
        self.editorPlaceholder = qt.QLabel("Editor will initialize when you first visit this module...")
        self.editorPlaceholder.setMinimumHeight(350)
        self.editorPlaceholder.setAlignment(qt.Qt.AlignCenter)
        self.editorPlaceholder.setStyleSheet("background-color: #f5f5f5; color: #666; border: 1px dashed #ccc;")
        editorLayout.addWidget(self.editorPlaceholder)
        
        # Store layout reference for lazy editor creation
        self.editorLayout = editorLayout
        
        # DON'T connect node selector here - it will interfere with other modules
        # Connection will be made on first enter() to avoid premature observer setup
        self._nodeSelectorConnected = False
        
        editorContainer.setMinimumHeight(450)
        devFormLayout.addRow(editorContainer)

        # Connections
        self.sendButton.clicked.connect(self.onSendPromptButtonClicked)

        self.layout.addStretch(1)
    
    def enter(self):
        """Called when the user switches to this module - restore observers"""
        # Initialize editor on first visit
        if not self.editorInitialized:
            self.initializeEditor()
            return  # initializeEditor will call enter() again after setup
        
        # Connect node selector on first entry only (after editor is ready)
        if not self._nodeSelectorConnected:
            self.scriptNodeSelector.currentNodeChanged.connect(self.onScriptNodeChanged)
            self._nodeSelectorConnected = True
        
        # Restart timers if they exist
        if hasattr(self, 'contextMenuTimer') and self.contextMenuTimer:
            if not self.contextMenuTimer.isActive():
                self.contextMenuTimer.start(400)
        
        if hasattr(self, 'changeCheckTimer') and self.changeCheckTimer:
            if not self.changeCheckTimer.isActive():
                self.changeCheckTimer.start(1000)
        
        # Restore observer on current node if we have one
        if hasattr(self, '_currentObservedNode') and self._currentObservedNode:
            # Remove any existing observer first (in case it wasn't cleaned up)
            if hasattr(self, '_nodeModifiedTag') and self._nodeModifiedTag:
                try:
                    self._currentObservedNode.RemoveObserver(self._nodeModifiedTag)
                except:
                    pass
            # Add new observer
            self._nodeModifiedTag = self._currentObservedNode.AddObserver(
                vtk.vtkCommand.ModifiedEvent, self.onNodeContentModified)
            # Refresh editor content
            self.refreshEditorFromNode(self._currentObservedNode)
        else:
            # First time entering - check if node selector has a node selected
            currentNode = self.scriptNodeSelector.currentNode()
            if currentNode:
                # Trigger the node changed handler to set everything up
                self.onScriptNodeChanged(currentNode)
    
    def initializeEditor(self):
        """Lazy initialization of Monaco editor on first module visit"""
        print("🔧 Initializing DeveloperAgent Monaco editor...")
        
        # Remove placeholder
        self.editorLayout.removeWidget(self.editorPlaceholder)
        self.editorPlaceholder.deleteLater()
        
        # Create Monaco editor using qSlicerWebWidget
        self.codeEditor = slicer.qSlicerWebWidget()
        self.codeEditor.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.codeEditor.setMinimumHeight(350)
        
        # Get the Monaco editor HTML path from Script Editor
        try:
            modulePath = os.path.dirname(slicer.modules.scripteditor.path)
            editorHtmlPath = os.path.join(modulePath, 'Resources', 'monaco-editor', 'index.html')
            
            if os.path.exists(editorHtmlPath):
                self.codeEditor.url = qt.QUrl.fromLocalFile(editorHtmlPath)
                self.codeEditor.connect("evalResult(QString,QString)", self.onMonacoEvalResult)
                self.editorLayout.insertWidget(self.editorLayout.count() - 1, self.codeEditor)  # Insert before Execute button
                print("✅ Monaco editor loaded successfully")
                
                # Setup Monaco editor features after a delay
                qt.QTimer.singleShot(1500, self.setupMonacoFeatures)
                
                self.editorInitialized = True
                
                # Re-enter the module to complete setup
                qt.QTimer.singleShot(2000, self.enter)
            else:
                raise FileNotFoundError("Monaco editor HTML not found")
        except Exception as e:
            print(f"⚠️ Could not load Monaco editor: {e}")
            # Fallback to simple text editor
            self.codeEditor = qt.QTextEdit()
            self.codeEditor.setMinimumHeight(350)
            font = qt.QFont("Courier")
            font.setStyleHint(qt.QFont.Monospace)
            font.setFixedPitch(True)
            font.setPointSize(10)
            self.codeEditor.setFont(font)
            self.editorLayout.insertWidget(self.editorLayout.count() - 1, self.codeEditor)
            
            self.editorInitialized = True
            # Re-enter immediately for fallback editor
            self.enter()
    
    def exit(self):
        """Called when the user switches away from this module - clean up observers"""
        # Stop timers to reduce unnecessary processing when module is inactive
        if hasattr(self, 'contextMenuTimer') and self.contextMenuTimer:
            self.contextMenuTimer.stop()
        
        if hasattr(self, 'changeCheckTimer') and self.changeCheckTimer:
            self.changeCheckTimer.stop()
        
        # Remove observer to avoid interfering with other modules
        if hasattr(self, '_currentObservedNode') and self._currentObservedNode:
            if hasattr(self, '_nodeModifiedTag') and self._nodeModifiedTag:
                try:
                    self._currentObservedNode.RemoveObserver(self._nodeModifiedTag)
                    self._nodeModifiedTag = None
                except:
                    pass
    
    def refreshEditorFromNode(self, node):
        """Refresh editor content from a node without triggering observers"""
        if not node:
            return
        
        text = node.GetText() if node.GetText() else ""
        
        if hasattr(self.codeEditor, 'evalJS'):
            # Monaco editor
            import json
            escaped_text = json.dumps(text)
            self.codeEditor.evalJS(f'if (window.editor && window.editor.getModel) {{ window.editor.getModel().setValue({escaped_text}); }}')
        elif hasattr(self.codeEditor, 'setPlainText'):
            # QTextEdit fallback
            try:
                self.codeEditor.textChanged.disconnect()
            except:
                pass
            self.codeEditor.setPlainText(text)
            if node:
                self.codeEditor.textChanged.connect(lambda: self.onCodeEdited(node))

    def setupMonacoFeatures(self):
        """Setup Monaco editor features after it's loaded"""
        # Set initial theme to light
        self.setTheme("vs")
        
        # Set initial font size
        self.setFontSize(14)
        
        # Setup context menu for sending code to Python console
        self.setupContextMenu()
        
        # Setup change detection to save content back to node
        self.setupChangeDetection()
        
        # Setup timer to check for selected code
        self.contextMenuTimer = qt.QTimer()
        self.contextMenuTimer.timeout.connect(self.checkForSelectedCode)
        self.contextMenuTimer.start(400)
        
        # Disable editor until a node is selected
        self.setEditorEnabled(False)
    
    def setupContextMenu(self):
        """Setup Monaco editor context menu with 'Send to Python Console' option"""
        contextMenuScript = """
        (function() {
            try {
                if (!window.editor || typeof window.editor.addAction !== 'function') {
                    console.log('Editor not ready, retrying in 1 second...');
                    setTimeout(arguments.callee, 1000);
                    return;
                }
                
                window.getSelectedText = function() {
                    try {
                        if (window.editor && typeof window.editor.getSelection === 'function' && typeof window.editor.getModel === 'function') {
                            var selection = window.editor.getSelection();
                            if (selection && window.editor.getModel()) {
                                return window.editor.getModel().getValueInRange(selection);
                            }
                        }
                    } catch (e) {
                        console.log('Error getting selected text:', e);
                    }
                    return '';
                };
                
                window.editor.addAction({
                    id: 'send-to-python-console',
                    label: 'Send Selection to Python Console',
                    contextMenuGroupId: 'navigation',
                    contextMenuOrder: 1.5,
                    keybindings: [
                        monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter
                    ],
                    run: function(editor) {
                        try {
                            if (editor && typeof editor.getSelection === 'function' && typeof editor.getModel === 'function') {
                                var selection = editor.getSelection();
                                var model = editor.getModel();
                                if (selection && model) {
                                    var selectedText = model.getValueInRange(selection);
                                    if (selectedText) {
                                        window.selectedCodeForExecution = selectedText;
                                    }
                                }
                            }
                        } catch (e) {
                            console.log('Error in context menu action:', e);
                        }
                        return null;
                    }
                });
                console.log('Context menu action registered successfully');
            } catch (e) {
                console.log('Error setting up context menu:', e);
            }
        })();
        """
        if hasattr(self.codeEditor, 'evalJS'):
            self.codeEditor.evalJS(contextMenuScript)
    
    def setupChangeDetection(self):
        """Setup Monaco editor to detect content changes and save to node"""
        changeDetectionScript = """
        (function() {
            try {
                if (!window.editor || typeof window.editor.onDidChangeModelContent !== 'function') {
                    console.log('Editor not ready for change detection, retrying in 1 second...');
                    setTimeout(arguments.callee, 1000);
                    return;
                }
                
                window.editor.onDidChangeModelContent(function(e) {
                    try {
                        if (window.changeTimeout) {
                            clearTimeout(window.changeTimeout);
                        }
                        window.changeTimeout = setTimeout(function() {
                            try {
                                window.contentChanged = true;
                                if (window.editor && typeof window.editor.getModel === 'function' && window.editor.getModel()) {
                                    var content = window.editor.getModel().getValue();
                                    window.currentEditorContent = content;
                                }
                            } catch (e) {
                                console.log('Error in change timeout:', e);
                            }
                        }, 1000);
                    } catch (e) {
                        console.log('Error in change detection callback:', e);
                    }
                });
                
                console.log('Change detection initialized');
            } catch (e) {
                console.log('Error setting up change detection:', e);
            }
        })();
        """
        if hasattr(self.codeEditor, 'evalJS'):
            self.codeEditor.evalJS(changeDetectionScript)
            
            # Setup timer to check for content changes
            self.changeCheckTimer = qt.QTimer()
            self.changeCheckTimer.timeout.connect(self.checkForContentChanges)
            self.changeCheckTimer.start(1000)
    
    def checkForContentChanges(self):
        """Check if Monaco content has changed and save to node"""
        if hasattr(self.codeEditor, 'evalJS'):
            self.codeEditor.evalJS("window.contentChanged || false")
    
    def onMonacoEvalResult(self, request, result):
        """Handle results from Monaco editor JavaScript evaluation"""
        # Check if this is selected code from context menu
        if request == "window.selectedCodeForExecution || ''":
            if result and result.strip():
                # Clear the flag FIRST to prevent re-execution
                if hasattr(self.codeEditor, 'evalJS'):
                    self.codeEditor.evalJS("window.selectedCodeForExecution = null;")
                self.executeInPythonConsole(result)
        # Check if this is content change detection
        elif request == "window.contentChanged || false":
            if result == "true":
                # Content has changed - get the current content
                if hasattr(self.codeEditor, 'evalJS'):
                    self.codeEditor.evalJS("window.currentEditorContent || ''")
        elif request == "window.currentEditorContent || ''":
            # This is the actual content - save it to the node
            node = self.scriptNodeSelector.currentNode()
            if node and result:
                self._isSyncing = True
                node.SetText(result)
                self._isSyncing = False
                # Reset the flags
                if hasattr(self.codeEditor, 'evalJS'):
                    self.codeEditor.evalJS("window.contentChanged = false; window.currentEditorContent = null;")
    
    def checkForSelectedCode(self):
        """Check if there's selected code to execute from the context menu"""
        if hasattr(self.codeEditor, 'evalJS'):
            self.codeEditor.evalJS("window.selectedCodeForExecution || ''")
    
    def executeInPythonConsole(self, code):
        """Execute selected code directly in Python console"""
        try:
            if code and code.strip():
                # Print the code being executed
                print("Executing:")
                print(code)
                print("-" * 40)
                
                exec(code, {'slicer': slicer, 'logging': logging, '__name__': '__main__'})
        except Exception as e:
            import traceback
            error_msg = f"Error executing code:\n{str(e)}\n{traceback.format_exc()}"
            print(error_msg)
    
    def onThemeChanged(self):
        """Handle theme radio button changes"""
        if self.lightThemeRadio.isChecked():
            self.setTheme("vs")
        else:
            self.setTheme("vs-dark")
    
    def onFontSizeChanged(self, value):
        """Handle font size slider changes"""
        self.fontSizeValueLabel.setText(str(value))
        self.setFontSize(value)
    
    def setTheme(self, themeName):
        """Set the Monaco editor theme"""
        if hasattr(self.codeEditor, 'evalJS'):
            themeScript = f"""
            (function() {{
                try {{
                    if (window.monaco && window.monaco.editor && typeof window.monaco.editor.setTheme === 'function') {{
                        monaco.editor.setTheme('{themeName}');
                        console.log('Theme set to: {themeName}');
                    }} else {{
                        console.log('Editor not ready for theme change');
                    }}
                }} catch (e) {{
                    console.log('Error setting theme:', e);
                }}
            }})();
            """
            self.codeEditor.evalJS(themeScript)
    
    def setFontSize(self, size):
        """Set the Monaco editor font size"""
        if hasattr(self.codeEditor, 'evalJS'):
            fontSizeScript = f"""
            (function() {{
                try {{
                    if (window.monaco && window.editor && typeof window.editor.updateOptions === 'function') {{
                        window.editor.updateOptions({{ fontSize: {size} }});
                        console.log('Font size set to: {size}px');
                    }} else {{
                        console.log('Editor not ready for font size change');
                    }}
                }} catch (e) {{
                    console.log('Error setting font size:', e);
                }}
            }})();
            """
            self.codeEditor.evalJS(fontSizeScript)
    
    def onExecuteScript(self):
        """Execute the current script in Python console"""
        try:
            node = self.scriptNodeSelector.currentNode()
            if not node:
                slicer.util.warningDisplay("No script node selected")
                return
            
            code = node.GetText()
            if not code or not code.strip():
                slicer.util.warningDisplay("Script is empty")
                return
            
            # Execute in Python console
            exec(code, {'slicer': slicer, 'logging': logging, '__name__': '__main__'})
            print(f"✅ Executed: {node.GetName()}")
        except Exception as e:
            import traceback
            error_msg = f"Error executing script:\n{str(e)}\n{traceback.format_exc()}"
            slicer.util.errorDisplay(error_msg)
            print(error_msg)
    
    def onScriptNodeChanged(self, node):
        """Called when the script node selector changes"""
        # Remove observer from previous node
        if hasattr(self, '_currentObservedNode') and self._currentObservedNode:
            try:
                self._currentObservedNode.RemoveObserver(self._nodeModifiedTag)
            except:
                pass
        
        if node:
            # Enable editor when node is selected
            self.setEditorEnabled(True)
            
            # Observe node modifications
            self._currentObservedNode = node
            self._nodeModifiedTag = node.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onNodeContentModified)
            
            # Use refreshEditorFromNode for consistent content loading
            self.refreshEditorFromNode(node)
        else:
            # Disable editor when no node is selected
            self.setEditorEnabled(False)
            # Clear editor content
            if hasattr(self.codeEditor, 'evalJS'):
                self.codeEditor.evalJS('if (window.editor && window.editor.getModel) { window.editor.getModel().setValue(""); }')
            elif hasattr(self.codeEditor, 'setPlainText'):
                self.codeEditor.setPlainText("")
            
            self._currentObservedNode = None
    
    def onNodeContentModified(self, caller, event):
        """Called when the text node content is modified"""
        if self._isSyncing:
            return  # Skip if we're already syncing to prevent circular updates
        
        node = caller
        if node and hasattr(self.codeEditor, 'evalJS'):
            self._isSyncing = True
            text = node.GetText() if node.GetText() else ""
            import json
            escaped_text = json.dumps(text)
            # Temporarily disable change detection while updating
            self.codeEditor.evalJS(f'window.contentChanged = false; if (window.editor && window.editor.getModel) {{ window.editor.getModel().setValue({escaped_text}); }}')
            self._isSyncing = False
        elif node and hasattr(self.codeEditor, 'setPlainText'):
            self._isSyncing = True
            self.codeEditor.setPlainText(node.GetText() if node.GetText() else "")
            self._isSyncing = False
    
    def onCodeEdited(self, node):
        """Save edited code back to the node (for QTextEdit fallback)"""
        if node and hasattr(self.codeEditor, 'toPlainText'):
            node.SetText(self.codeEditor.toPlainText())
    
    def setEditorEnabled(self, enabled):
        """Enable or disable the Monaco editor"""
        if hasattr(self.codeEditor, 'evalJS'):
            # For Monaco editor, use JavaScript to enable/disable
            if enabled:
                self.codeEditor.evalJS('if (window.editor) { window.editor.updateOptions({ readOnly: false }); }')
            else:
                self.codeEditor.evalJS('if (window.editor) { window.editor.updateOptions({ readOnly: true }); }')
        elif hasattr(self.codeEditor, 'setEnabled'):
            # For QTextEdit fallback
            self.codeEditor.setEnabled(enabled)
    
    def updateEditorContent(self, node):
        """Update Monaco editor to display the node's content"""
        if node and hasattr(self.codeEditor, 'evalJS'):
            text = node.GetText() if node.GetText() else ""
            import json
            escaped_text = json.dumps(text)
            self.codeEditor.evalJS(f'if (window.editor && window.editor.getModel) {{ window.editor.getModel().setValue({escaped_text}); }}')
    
    def forceEditorUpdate(self, node):
        """Force update the Monaco editor with the node's current content"""
        if not node:
            return
        
        text = node.GetText() if node.GetText() else ""
        
        # Process any pending Qt events first
        slicer.app.processEvents()
        
        if hasattr(self.codeEditor, 'evalJS'):
            # Monaco editor - force update via JavaScript
            import json
            escaped_text = json.dumps(text)
            updateScript = f'''
            (function() {{
                try {{
                    if (window.editor && window.editor.getModel) {{
                        window.editor.getModel().setValue({escaped_text});
                        console.log("Editor content updated, length: {len(text)} chars");
                    }} else {{
                        console.log("Editor not ready yet");
                    }}
                }} catch (e) {{
                    console.log("Error updating editor:", e);
                }}
            }})();
            '''
            self.codeEditor.evalJS(updateScript)
            
            # Give the editor time to process
            slicer.app.processEvents()
            
        elif hasattr(self.codeEditor, 'setPlainText'):
            # QTextEdit fallback
            self.codeEditor.setPlainText(text)
        
        print(f"✅ Force updated editor with {len(text)} characters")
    
    def getCurrentScriptNode(self):
        """Get current script node from embedded editor, or create new one"""
        try:
            # Get from node selector
            node = self.scriptNodeSelector.currentNode()
            if node:
                return node
            
            # Create new node if none selected
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextNode')
            node.SetName(f"AIScript_{timestamp}.py")
            node.SetAttribute("mimetype", "text/x-python")
            node.SetText("# AI generated script\n")
            
            # Set as current in selector
            self.scriptNodeSelector.setCurrentNode(node)
            
            return node
        except Exception as e:
            self.conversationView.append(f"Error getting script node: {e}")
            return None
    
    def appendToConversationView(self, message):
        """Append a message to the conversation view"""
        self.conversationView.append(f"<pre>{message}</pre>")
        self.conversationView.verticalScrollBar().setValue(
            self.conversationView.verticalScrollBar().maximum)
        slicer.app.processEvents()



    def onBrowseOutputPath(self):
        """Browse for output directory"""
        dialog = qt.QFileDialog()
        dialog.setFileMode(qt.QFileDialog.Directory)
        dialog.setOption(qt.QFileDialog.ShowDirsOnly, True)
        if dialog.exec_():
            selected_dir = dialog.selectedFiles()[0]
            self.outputPathLineEdit.setText(selected_dir)
            # Save the selected path to settings
            settings = qt.QSettings()
            settings.setValue("DeveloperAgent/outputPath", selected_dir)

    def onDebugScriptEditor(self):
        """Debug Script Editor widget structure"""
        self.logic.debugScriptEditor()

    def checkForOpenAILibrary(self):
        """Check if the openai library is installed (needed for GitHub Models API)"""
        try:
            from openai import OpenAI
        except ImportError:
            self.showInstallMessage()

    def checkForScriptEditor(self):
        """Check if Script Editor extension is available and offer to install"""
        if not hasattr(slicer.modules, 'scripteditor'):
            msg = qt.QMessageBox()
            msg.setIcon(qt.QMessageBox.Information)
            msg.setText("Script Editor Extension Required")
            msg.setInformativeText(
                "The Script Editor extension is required for the best experience with DeveloperAgent.\n\n"
                "This extension provides:\n"
                "• Syntax highlighting for Python code\n"
                "• Easy script editing and execution\n"
                "• Better integration with generated scripts\n\n"
                "Would you like to install it now?"
            )
            msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
            msg.setDefaultButton(qt.QMessageBox.Yes)
            
            if msg.exec_() == qt.QMessageBox.Yes:
                self.installScriptEditor()
    
    def installScriptEditor(self):
        """Install the Script Editor extension"""
        try:
            self.conversationView.append("<b>� Installing Script Editor extension...</b>")
            slicer.app.processEvents()
            
            # Get the extensions manager
            extensionsManager = slicer.app.extensionsManagerModel()
            if not extensionsManager:
                self.conversationView.append(
                    "<span style='color: red;'>❌ Could not access Extensions Manager. "
                    "Please install Script Editor manually from Extensions Manager.</span>"
                )
                return
            
            # Try to install the extension
            extensionName = "ScriptEditor"
            
            # Check if already installed but not loaded
            if extensionsManager.isExtensionInstalled(extensionName):
                self.conversationView.append(
                    "<span style='color: orange;'>⚠️ Script Editor is already installed but may need a restart. "
                    "Please restart 3D Slicer to use the extension.</span>"
                )
                return
            
            # Install the extension
            self.conversationView.append(f"<i>Searching for {extensionName} extension...</i>")
            slicer.app.processEvents()
            
            # Schedule the download
            success = extensionsManager.downloadAndInstallExtensionByName(extensionName)
            
            if success:
                self.conversationView.append(
                    "<span style='color: green;'>✅ Script Editor extension installed successfully!</span><br>"
                    "<b>⚠️ Please restart 3D Slicer to use the extension.</b>"
                )
            else:
                self.conversationView.append(
                    "<span style='color: red;'>❌ Automatic installation failed. "
                    "Please install Script Editor manually:<br>"
                    "1. Go to Extensions Manager (View → Extension Manager)<br>"
                    "2. Click 'Install Extensions'<br>"
                    "3. Search for 'Script Editor'<br>"
                    "4. Click Install</span>"
                )
                
        except Exception as e:
            self.conversationView.append(
                f"<span style='color: red;'>❌ Error installing Script Editor: {str(e)}<br>"
                "Please install manually from Extensions Manager.</span>"
            )

    def showInstallMessage(self):
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("OpenAI Library Not Found")
        msg.setInformativeText("The 'openai' library is required for GitHub Models API. Would you like to install it now?")
        msg.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
        if msg.exec_() == qt.QMessageBox.Ok:
            self.conversationView.append("<b>Installing 'openai' library (for GitHub Models API)...</b>")
            slicer.util.pip_install('openai')
            self.conversationView.append("<b>Installation complete.</b>")



    def onSendPromptButtonClicked(self):
        apiKey = self.apiKeyLineEdit.text.strip()
        userPrompt = self.promptTextEdit.toPlainText().strip()
        outputPath = self.outputPathLineEdit.text.strip()

        # Check if API key is needed based on selected model
        selected_model = self.modelSelector.currentData
        jetstream_models = ["DeepSeek-R1", "gpt-oss-120b", "llama-4-scout"]
        
        if not apiKey and selected_model not in jetstream_models:
            slicer.util.warningDisplay("Please enter your GitHub Personal Access Token for non-Jetstream2 models.")
            return
        if not userPrompt:
            slicer.util.warningDisplay("Please enter a development prompt.")
            return
        if not outputPath:
            slicer.util.warningDisplay("Please specify an output directory.")
            return
        
        # Get or create text node from embedded editor
        currentNode = self.getCurrentScriptNode()
        if not currentNode:
            slicer.util.warningDisplay("Could not get or create script node.")
            return
        
        # Get current code if checkbox is checked
        currentCode = None
        if self.includeCurrentCodeCheckbox.isChecked():
            currentCode = currentNode.GetText() if currentNode.GetText() else ""
            if not currentCode.strip():
                self.conversationView.append("<i>⚠️ 'Include current code' is checked but editor is empty. Generating new code instead.</i><br>")
                currentCode = None
        
        scriptName = currentNode.GetName().replace('.py', '')
        
        # Validate that the output path is accessible
        try:
            if not os.path.exists(outputPath):
                os.makedirs(outputPath)
            elif not os.path.isdir(outputPath):
                slicer.util.warningDisplay(f"Output path is not a directory: {outputPath}")
                return
        except Exception as e:
            slicer.util.warningDisplay(f"Cannot access output directory: {str(e)}")
            return

        self.sendButton.enabled = False
        
        # Update logic with current settings
        self.logic.setDebugIterations(self.debugIterationsSpinBox.value)
        self.logic.setModel(self.modelSelector.currentData)
        
        display_target = scriptName
        mode = "Improving Existing Code" if currentCode else "Generating New Script"
            
        self.conversationView.append(f"<h2>New Request</h2><b>Mode:</b> {mode}<br>"
                                     f"<b>Script:</b> {display_target}<br>"
                                     f"<b>Request:</b> {userPrompt}<br>"
                                     f"<i>Processing, please wait...</i><hr>")
        slicer.app.processEvents()

        try:
            result = self.logic.processRequestToNode(apiKey, userPrompt, currentNode, outputPath, currentCode)
            
            # ALWAYS update the editor to show generated code (even if execution failed)
            self.forceEditorUpdate(currentNode)
            
            if result['success']:
                self.conversationView.append(f"✅ <b>Success!</b><br>{result['message']}<hr>")
            else:
                self.conversationView.append(f"❌ <b>Failed.</b><br>"
                                             f"<b>Final Error:</b><br><pre>{result['error']}</pre><hr>")
                self.conversationView.append(f"<b>ℹ️ Generated code has been loaded in the editor above for manual review and debugging.</b><hr>")
        except Exception as e:
            self.conversationView.append(f"❌ <b>An unexpected error occurred:</b><br><pre>{e}</pre><hr>")
            logging.error(f"DeveloperAgent unexpected error: {e}", exc_info=True)

        self.promptTextEdit.clear()
        self.sendButton.enabled = True
        self.conversationView.verticalScrollBar().setValue(self.conversationView.verticalScrollBar().maximum)

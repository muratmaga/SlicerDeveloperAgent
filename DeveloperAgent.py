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
                'default_model': getattr(slicer_prompts, 'DEFAULT_MODEL', 'gpt-4o'),
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
                ("GPT-4o (Recommended)", "gpt-4o"),
                ("GPT-4o Mini", "gpt-4o-mini"),
            ],
            'default_model': 'gpt-4o',
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
            default_model = getattr(slicer_prompts, 'DEFAULT_MODEL', 'gpt-4o')
        else:
            default_model = 'gpt-4o'
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
        self.debugIterationsSpinBox.setMinimum(1)
        self.debugIterationsSpinBox.setMaximum(10)
        self.debugIterationsSpinBox.setValue(2)
        self.debugIterationsSpinBox.setToolTip("Number of debug attempts when code generation fails (default: 2)")
        setupFormLayout.addRow("Debug Iterations:", self.debugIterationsSpinBox)
        
        # --- Model Selection ---
        self.modelSelector = qt.QComboBox()
        # Load models from configuration
        prompts = self.logic._get_prompts()
        available_models = prompts.get('available_models', [("GPT-4o", "gpt-4o")])
        default_model = prompts.get('default_model', 'gpt-4o')
        
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

        # --- Python Script Creation ---
        devFormLayout.addRow(qt.QLabel("<b>Create a Python Script</b>"))
        self.scriptNameLineEdit = qt.QLineEdit()
        self.scriptNameLineEdit.setPlaceholderText("e.g., MyDataProcessor")
        devFormLayout.addRow("Script Name:", self.scriptNameLineEdit)
        
        # Add info about Script Editor integration
        script_editor_info = qt.QLabel("💡 Scripts will automatically open in Script Editor extension if available")
        script_editor_info.setStyleSheet("color: #666; font-style: italic; font-size: 10px;")
        script_editor_info.setWordWrap(True)
        devFormLayout.addRow(script_editor_info)
        
        # Add GitHub token help
        github_token_info = qt.QLabel("🔑 GitHub Token: Go to github.com/settings/tokens → Generate new token (classic) → Select 'repo' scope → Using GPT-4o via GitHub Models (excellent for coding)")
        github_token_info.setStyleSheet("color: #0366d6; font-size: 10px;")
        github_token_info.setWordWrap(True)
        devFormLayout.addRow(github_token_info)
        
        # Script Editor quick-open button
        debug_layout = qt.QHBoxLayout()
        # New: Open the most recent generated script in Script Editor and auto-select it
        self.openInScriptEditorButton = qt.QPushButton("Open in Script Editor")
        self.openInScriptEditorButton.setToolTip("Switch to Script Editor and display the last generated script")
        self.openInScriptEditorButton.clicked.connect(self.onOpenInScriptEditorClicked)

        debug_layout.addWidget(self.openInScriptEditorButton)
        devFormLayout.addRow(debug_layout)

        # --- Conversation UI ---
        devFormLayout.addRow(qt.QLabel("<b>Conversation & Prompt</b>"))
        self.conversationView = qt.QTextBrowser()
        self.conversationView.setMinimumHeight(300)
        devFormLayout.addRow(self.conversationView)
        
        # Check for required libraries and extensions (after conversationView is created)
        self.checkForOpenAILibrary()
        self.checkForScriptEditor()
        
        self.promptTextEdit = qt.QTextEdit()
        # --- Pre-populated Prompt ---
        self.promptTextEdit.setPlainText("Create a script that downloads data from a URL and renders it in 3D using a single 3D view layout. Use this default URL: https://raw.githubusercontent.com/SlicerMorph/SampleData/refs/heads/master/IMPC_sample_data.nrrd")
        self.promptTextEdit.setFixedHeight(100)
        devFormLayout.addRow(self.promptTextEdit)
        self.sendButton = qt.QPushButton("🚀 Generate Python Script (GPT-4o via GitHub)")
        devFormLayout.addRow(self.sendButton)

        # Connections
        self.sendButton.clicked.connect(self.onSendPromptButtonClicked)

        self.layout.addStretch(1)

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
    
    def onOpenInScriptEditorClicked(self):
        """Open the last generated script in Script Editor and auto-select its node."""
        try:
            # Prefer the exact last node created/updated
            nodeId = getattr(self.logic, 'lastScriptNodeID', None)
            filePath = getattr(self.logic, 'lastScriptFilePath', None)

            if nodeId:
                self.logic.focusScriptInScriptEditor(nodeId)
                return

            # If we only know the file path, ensure it is in the scene and focus it
            if filePath and os.path.exists(filePath):
                node, _ = self.logic.loadScriptIntoScene(filePath)
                if node:
                    self.logic.lastScriptNodeID = node.GetID()
                    self.logic.lastScriptFilePath = filePath
                    self.logic.focusScriptInScriptEditor(node)
                    return

            # Fallback: choose any Python text node if available
            pyNodes = [n for n in slicer.util.getNodesByClass('vtkMRMLTextNode') if n.GetAttribute('mimetype') == 'text/x-python']
            if pyNodes:
                self.logic.focusScriptInScriptEditor(pyNodes[0])
                return

            slicer.util.warningDisplay("No generated script available to open. Please create a script first.")
        except Exception as e:
            slicer.util.warningDisplay(f"Could not open Script Editor: {e}")


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
        scriptName = self.scriptNameLineEdit.text.strip()
        outputPath = self.outputPathLineEdit.text.strip()

        if not apiKey:
            slicer.util.warningDisplay("Please enter your GitHub Personal Access Token.")
            return
        if not userPrompt:
            slicer.util.warningDisplay("Please enter a development prompt.")
            return
        if not scriptName:
            slicer.util.warningDisplay("Please enter a 'Script Name'.")
            return
        if not outputPath:
            slicer.util.warningDisplay("Please specify an output directory.")
            return
        
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
        action_type = "Creating Script"
            
        self.conversationView.append(f"<h2>New Request</h2><b>{action_type}:</b> {display_target}<br>"
                                     f"<b>Prompt:</b> {userPrompt}<br>"
                                     f"<i>Processing, please wait...</i><hr>")
        slicer.app.processEvents()

        try:
            result = self.logic.processRequest(apiKey, userPrompt, scriptName, outputPath)
            if result['success']:
                self.conversationView.append(f"✅ <b>Success!</b><br>{result['message']}<hr>")
            else:
                self.conversationView.append(f"❌ <b>Failed.</b><br>"
                                             f"<b>Final Error:</b><br><pre>{result['error']}</pre><hr>")
        except Exception as e:
            self.conversationView.append(f"❌ <b>An unexpected error occurred:</b><br><pre>{e}</pre><hr>")
            logging.error(f"DeveloperAgent unexpected error: {e}", exc_info=True)

        self.promptTextEdit.clear()
        self.sendButton.enabled = True
        self.conversationView.verticalScrollBar().setValue(self.conversationView.verticalScrollBar().maximum)

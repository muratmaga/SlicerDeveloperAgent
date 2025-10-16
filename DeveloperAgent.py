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

#
# DeveloperAgent
#

class DeveloperAgent(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Developer Agent"
        self.parent.categories = ["Developer Tools"]
        self.parent.dependencies = ["ExtensionWizard"] # Add dependency
        self.parent.contributors = ["AI Assistant"]
        self.parent.helpText = "This module was created by DeveloperAgent."
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
        return getattr(self, '_model', 'gpt-4o')

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

    def processRequest(self, apiKey, userPrompt, newModuleName=None, targetModuleName=None, scriptName=None, outputPath=None):
        try:
            from openai import OpenAI
            # Use GitHub Models API (included with GitHub Copilot subscription)
            client = OpenAI(
                api_key=apiKey,
                base_url="https://models.inference.ai.azure.com"
            )
        except ImportError:
            return {"success": False, "error": "OpenAI library not found. Please install it with: pip install openai"}
        except Exception as e:
            return {"success": False, "error": f"Failed to initialize GitHub Models client: {str(e)}"}

        if newModuleName:
            return self.createNewModule(client, userPrompt, newModuleName, outputPath)
        elif targetModuleName:
            return self.modifyExistingModule(client, userPrompt, targetModuleName)
        elif scriptName:
            return self.createSimpleScript(client, userPrompt, scriptName, outputPath)
        return {"success": False, "error": "No target module, new module name, or script name specified."}

    def testModuleFunctionality(self, moduleName):
        """Test basic module functionality and capture any runtime errors"""
        import traceback  # Ensure traceback is available in this scope
        try:
            self.diagnostic_print(f"Testing module '{moduleName}' functionality...")
            
            # Get the module's widget representation
            self.diagnostic_print("  - Getting module widget...")
            moduleWidget = slicer.util.getModuleWidget(moduleName)
            if not moduleWidget:
                raise RuntimeError(f"Could not get widget for module {moduleName}")
            
            # Try to access key components that should exist
            if not hasattr(moduleWidget, 'logic'):
                raise RuntimeError("Module widget missing 'logic' attribute")
            
            # Test the setup method and monitor for runtime errors
            self.diagnostic_print("  - Running module setup and monitoring for errors...")
            error_buffer = StringIO()
            runtime_error = None

            # Set up error monitoring
            errorLogModel = slicer.app.errorLogModel()
            def error_handler(msg_type, msg_text):
                if msg_type in ['ERROR', 'FATAL', 'WARNING']:
                    error_buffer.write(f"[{msg_type}] {msg_text}\n")
                    
            observer = errorLogModel.connect('messageLogged(QString, QString)', error_handler)

            try:
                # Run setup and wait for potential asynchronous errors
                moduleWidget.setup()
                slicer.app.processEvents()
                qt.QThread.msleep(1000)  # Wait a second for potential async operations
                slicer.app.processEvents()

                # Check error buffer
                if error_buffer.getvalue():
                    runtime_error = f"Runtime errors detected:\n{error_buffer.getvalue()}"
            finally:
                # Disconnect the error observer
                errorLogModel.disconnect(observer)

                # Check for any errors that occurred
            if runtime_error:
                raise RuntimeError(runtime_error)
                
            self.diagnostic_print("  ✓ Module tests completed successfully")
            return True, ""
            
        except Exception as e:
            error_msg = f"Runtime test failed: {str(e)}\n{traceback.format_exc()}"
            self.diagnostic_print(f"  ❌ {error_msg}", error=True)
            return False, error_msg

    def createNewModule(self, client, userPrompt, newModuleName, outputPath=None):
        import traceback  # Ensure traceback is available in this scope
        boilerplate = self.get_module_boilerplate(newModuleName)
        
        if outputPath:
            # Use custom output path with Modules/ModuleName/ModuleName.py structure
            moduleTopLevelDir = os.path.join(outputPath, "Modules", newModuleName)
            filePath = os.path.join(moduleTopLevelDir, f"{newModuleName}.py")
        else:
            # Fallback to default Slicer modules directory
            settings_dir = os.path.dirname(slicer.app.slicerUserSettingsFilePath)
            moduleTopLevelDir = os.path.join(settings_dir, "qt-scripted-modules", newModuleName)
            filePath = os.path.join(moduleTopLevelDir, f"{newModuleName}.py")

        max_debug_attempts = self.getDebugIterations()
        current_code = None
        error_history = ""

        for attempt in range(max_debug_attempts + 1):  # +1 for initial attempt
            try:
                if attempt == 0:
                    prompt_for_creation = (
                        f"Create a complete 3D Slicer module named '{newModuleName}' that implements the following functionality: {userPrompt}. "
                        f"Use only modern, non-deprecated Slicer API calls. Return ONLY the complete Python code without any explanation or markdown formatting.")
                else:
                    prompt_for_creation = (
                        f"Debug and fix the 3D Slicer module code. The module should implement: {userPrompt}\n"
                        f"Use only modern, non-deprecated Slicer API calls. Current error (Debug Attempt {attempt}/{max_debug_attempts}):\n{error_history}")

                newCode = self.call_ai(client, prompt_for_creation, current_code or boilerplate, error_history, "module")
                if newCode is None:
                    return {"success": False, "error": "AI API call failed. Check the conversation log for details. This may be due to rate limits, invalid API key, or network issues."}

                # Create directory if it doesn't exist
                if not os.path.exists(moduleTopLevelDir):
                    os.makedirs(moduleTopLevelDir)

                # Write the new code
                self.write_code(filePath, newCode)
                current_code = newCode

                # Add module to the Python path if needed
                if moduleTopLevelDir not in sys.path:
                    sys.path.append(moduleTopLevelDir)

                # Try to load the module
                self.diagnostic_print(f"Attempt {attempt + 1}: Registering module...")
                factory = slicer.app.moduleManager().factoryManager()
                factory.registerModule(qt.QFileInfo(filePath))
                
                self.diagnostic_print(f"Attempt {attempt + 1}: Loading module...")
                factory.loadModules([newModuleName])
                
                # Try to select and test the module
                self.diagnostic_print(f"Attempt {attempt + 1}: Selecting module...")
                slicer.util.selectModule(newModuleName)
                
                # Test the module's runtime functionality
                test_success, test_error = self.testModuleFunctionality(newModuleName)
                if not test_success:
                    raise RuntimeError(f"Module loaded but failed runtime tests: {test_error}")
                
                # If we get here without exceptions, module loaded and tested successfully
                result_message = f"Module '{newModuleName}' created, loaded, and tested successfully"
                if attempt > 0:
                    result_message += f" after {attempt} debug attempts"
                
                if outputPath:
                    result_message += f".\n\nModule structure created:\n📁 {outputPath}/\n  └── 📁 Modules/\n      └── 📁 {newModuleName}/\n          └── 📄 {newModuleName}.py"
                else:
                    result_message += f". Saved in: {moduleTopLevelDir}"
                
                return {"success": True, "message": result_message}

            except Exception as e:
                error_msg = f"Error on attempt {attempt + 1}:\n{str(e)}\n{traceback.format_exc()}"
                self.diagnostic_print(f"Module creation/loading failed:\n{error_msg}", error=True)
                error_history = error_msg
                
                if attempt == max_debug_attempts:
                    return {"success": False, "error": f"Failed to create/load module after {max_debug_attempts} debug attempts. Final error: {str(e)}\n\nError History:\n{error_history}"}
                
                # Continue to next attempt

    def modifyExistingModule(self, client, userPrompt, moduleName):
        modulePath = slicer.util.modulePath(moduleName)
        initialCode = self.read_code(modulePath)
        currentCode = initialCode
        errorHistory = ""
        maxAttempts = self.getDebugIterations()
        for attempt in range(maxAttempts):
            newCode = self.call_ai(client, userPrompt, currentCode, errorHistory, "module")
            if newCode is None:
                return {"success": False, "error": "AI API call failed. Check the conversation log for details. This may be due to rate limits, invalid API key, or network issues."}
            self.write_code(modulePath, newCode)
            reloadResult = self.reload_and_capture(moduleName)
            if reloadResult["success"]:
                return {"success": True, "message": f"Module '{moduleName}' modified successfully."}
            errorHistory += f"\n--- Attempt {attempt + 1} Error ---\n{reloadResult['error']}"
            currentCode = newCode
        self.write_code(modulePath, initialCode)
        self.reload_and_capture(moduleName)
        return {"success": False, "error": errorHistory}

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
            self.diagnostic_print("Clearing scene for clean test execution...")
            slicer.mrmlScene.Clear(0)
            
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

    def get_module_boilerplate(self, moduleName):
        return f"""
import slicer
from slicer.ScriptedLoadableModule import *
import logging

class {moduleName}(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "{moduleName}"
        self.parent.categories = ["Examples"]
        self.parent.contributors = ["DeveloperAgent (AI)"]
        self.parent.helpText = "This module was created by DeveloperAgent."

class {moduleName}Widget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        pass

class {moduleName}Logic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
    pass
"""

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

    def call_ai(self, client, prompt, code_context, error_history, request_type="module"):
        
        # DIAGNOSTIC: Log what we're sending to the AI
        self.diagnostic_print("=" * 80)
        self.diagnostic_print("AI CALL DIAGNOSTIC")
        self.diagnostic_print(f"Request Type: {request_type}")
        self.diagnostic_print(f"Prompt (first 200 chars): {prompt[:200]}...")
        self.diagnostic_print(f"Code Context Length: {len(code_context)} chars")
        self.diagnostic_print(f"Error History Length: {len(error_history)} chars")
        if error_history:
            self.diagnostic_print(f"Error History (first 500 chars): {error_history[:500]}...")
        self.diagnostic_print("=" * 80)
        
        base_prompt = """You are an expert 3D Slicer Python developer. 
        Respond ONLY with complete, working Python code that can be directly saved and executed.
        Do not include explanations, markdown formatting, or code blocks - just raw Python code.

        Essential imports: import slicer, slicer.util, logging
        For downloads: import SampleData
        Note: SampleData.downloadFromURL() returns a LIST of nodes, not a single node
        Example: volume_node = SampleData.downloadFromURL(url)[0]  # Get first node from list
        
        RESOURCES:
        - Official API documentation: https://slicer.readthedocs.io/en/latest/developer_guide/api.html
        - Script repository: https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html
        - Official Slicer source code repository https://github.com/Slicer/Slicer
        - When encountering AttributeError, check the exact class/method names in the documentation
        - VTK methods in Slicer use CapitalCase (e.g., GetID, SetVisibility, CreateNode)
        - When Python suggests "Did you mean: X?", use X exactly as suggested
        - For complex tasks, prefer slicer.util helper functions over low-level VTK APIs
        
        Focus on writing clean, working code that follows proper Python and Slicer patterns."""

        if request_type == "script":
            system_prompt = base_prompt + """

        SCRIPT REQUIREMENTS:
        - Standalone Python script for Slicer's Python console
        - Write code at module level (NO main() function, NO if __name__ == "__main__")
        - Execute statements directly in sequence for clear line-by-line error reporting
        - DO NOT use try/except blocks - let errors propagate naturally for debugging
        - DO NOT use slicer.util.errorDisplay() or slicer.util.infoDisplay() 
        - Use print() statements for output instead
        - Clear comments explaining each section
        - NO tuple unpacking without certainty about return values
        - Code should fail loudly if there are errors so they can be fixed
        """
        else:
            system_prompt = base_prompt + """

        MODULE REQUIREMENTS:
        - Full ScriptedLoadableModule implementation
        - Classes: ModuleName, ModuleNameWidget, ModuleNameLogic  
        - Inherit from ScriptedLoadableModule, ScriptedLoadableModuleWidget, ScriptedLoadableModuleLogic
        - Proper setup() method in Widget class
        - Complete module metadata (title, categories, contributors, helpText)
        - Qt widget patterns for UI
        - Logic separated from UI
        """

        user_prompt = f"""
## Task: {prompt}

## Error History (if any):
{error_history}

## Code Template/Context:
{code_context}

Generate working Slicer code that implements the requested functionality. Focus on correctness and proper API usage.
"""

        try:
            # Use AI-21 Jamba 1.5 Large or GPT-4o via GitHub Models (excellent for code development)
            # Note: GitHub Models available models include gpt-4o, gpt-4o-mini, AI21-Jamba-1.5-Large, etc.
            
            # DIAGNOSTIC: Log the full user prompt being sent
            full_user_message = f"""
## Task: {prompt}

## Error History (if any):
{error_history}

## Code Template/Context:
{code_context}

Generate working Slicer code that implements the requested functionality. Focus on correctness and proper API usage.
"""
            self.diagnostic_print(f"SENDING TO AI - Full message length: {len(full_user_message)} chars")
            
            # Get the model from settings
            model_name = self.getModel()
            self.diagnostic_print(f"Using AI model: {model_name}")
            
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_user_message}
                ],
                temperature=0.1,
                max_tokens=8000
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
        
        # Minimal validation - let runtime errors teach the AI
        
        # Check for missing essential imports
        if "import slicer" not in code:
            issues.append("Missing essential import: import slicer")
        
        # Check for basic Python syntax issues
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            issues.append(f"Syntax error: {str(e)}")
        
        return issues

    def reload_and_capture(self, module_name):
        import traceback  # Ensure traceback is available in this scope
        output_buffer = StringIO()
        success = False
        try:
            with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
                slicer.util.reloadScriptedModule(module_name)
                if "Traceback" not in output_buffer.getvalue():
                    success = True
        except:
            import traceback
            output_buffer.write(f"\n--- EXCEPTION DURING RELOAD ---\n{traceback.format_exc()}")
        return {"success": success, "error": output_buffer.getvalue()}

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
        self.modelSelector.addItem("GPT-4o (Recommended)", "gpt-4o")
        self.modelSelector.addItem("GPT-4o Mini (Faster, Lower Quota)", "gpt-4o-mini")
        self.modelSelector.addItem("GPT-4 Turbo", "gpt-4-turbo")
        self.modelSelector.addItem("AI21 Jamba 1.5 Large", "AI21-Jamba-1.5-Large")
        self.modelSelector.addItem("AI21 Jamba 1.5 Mini", "AI21-Jamba-1.5-Mini")
        self.modelSelector.setCurrentIndex(0)  # Default to GPT-4o
        self.modelSelector.setToolTip("Select the AI model to use for code generation. Different models have different rate limits and capabilities.")
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

        # --- Development Assistant ---
        devCollapsibleButton = ctk.ctkCollapsibleButton()
        devCollapsibleButton.text = "Development Assistant"
        devCollapsibleButton.collapsed = False
        self.layout.addWidget(devCollapsibleButton)
        devFormLayout = qt.QFormLayout(devCollapsibleButton)

        # --- New Module Creation ---
        devFormLayout.addRow(qt.QLabel("<b>Option 1: Create a New Module</b>"))
        self.newModuleNameLineEdit = qt.QLineEdit()
        self.newModuleNameLineEdit.setPlaceholderText("e.g., MyVolumeRenderer")
        devFormLayout.addRow("New Module Name:", self.newModuleNameLineEdit)

        # --- Existing Module Modification ---
        devFormLayout.addRow(qt.QLabel("<b>Option 2: Modify an Existing Module</b>"))
        self.targetModuleSelector = qt.QComboBox()
        self.populateModuleSelector()
        devFormLayout.addRow("Target Module:", self.targetModuleSelector)

        # --- Simple Python Script Creation ---
        devFormLayout.addRow(qt.QLabel("<b>Option 3: Create a Simple Python Script</b>"))
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
        self.sendButton = qt.QPushButton("🚀 Send Prompt to AI (GPT-4o via GitHub)")
        devFormLayout.addRow(self.sendButton)

        # Connections
        self.sendButton.clicked.connect(self.onSendPromptButtonClicked)
        self.newModuleNameLineEdit.textChanged.connect(self.onNewModuleNameChanged)
        self.targetModuleSelector.currentIndexChanged.connect(self.onTargetModuleChanged)
        self.scriptNameLineEdit.textChanged.connect(self.onScriptNameChanged)

        self.layout.addStretch(1)

    def appendToConversationView(self, message):
        """Append a message to the conversation view"""
        self.conversationView.append(f"<pre>{message}</pre>")
        self.conversationView.verticalScrollBar().setValue(
            self.conversationView.verticalScrollBar().maximum)
        slicer.app.processEvents()

    def onNewModuleNameChanged(self, text):
        has_text = bool(text)
        self.targetModuleSelector.enabled = not has_text
        self.scriptNameLineEdit.enabled = not has_text

    def onTargetModuleChanged(self, index):
        has_selection = index > 0
        self.newModuleNameLineEdit.enabled = not has_selection
        self.scriptNameLineEdit.enabled = not has_selection

    def onScriptNameChanged(self, text):
        has_text = bool(text)
        self.newModuleNameLineEdit.enabled = not has_text
        self.targetModuleSelector.enabled = not has_text

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

    def populateModuleSelector(self):
        self.targetModuleSelector.clear()
        self.targetModuleSelector.addItem("", None)
        moduleNames = slicer.app.moduleManager().modulesNames()
        scriptedModuleNames = []
        for name in moduleNames:
            if name == "DeveloperAgent":
                continue
            try:
                path = slicer.util.modulePath(name)
                if path and path.endswith('.py'):
                    scriptedModuleNames.append(name)
            except:
                continue
        scriptedModuleNames.sort()
        self.targetModuleSelector.addItems(scriptedModuleNames)

    def onSendPromptButtonClicked(self):
        apiKey = self.apiKeyLineEdit.text.strip()
        userPrompt = self.promptTextEdit.toPlainText().strip()
        newModuleName = self.newModuleNameLineEdit.text.strip()
        targetModuleName = self.targetModuleSelector.currentText
        scriptName = self.scriptNameLineEdit.text.strip()
        outputPath = self.outputPathLineEdit.text.strip()

        if not apiKey:
            slicer.util.warningDisplay("Please enter your GitHub Personal Access Token.")
            return
        if not userPrompt:
            slicer.util.warningDisplay("Please enter a development prompt.")
            return
        if not newModuleName and not targetModuleName and not scriptName:
            slicer.util.warningDisplay("Please either enter a 'New Module Name', select a 'Target Module', or enter a 'Script Name'.")
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
        
        if scriptName:
            display_target = scriptName
            action_type = "Creating Script"
        elif newModuleName:
            display_target = newModuleName
            action_type = "Creating Module"
        else:
            display_target = targetModuleName
            action_type = "Modifying Module"
            
        self.conversationView.append(f"<h2>New Request</h2><b>{action_type}:</b> {display_target}<br>"
                                     f"<b>Prompt:</b> {userPrompt}<br>"
                                     f"<i>Processing, please wait...</i><hr>")
        slicer.app.processEvents()

        try:
            result = self.logic.processRequest(apiKey, userPrompt, newModuleName, targetModuleName, scriptName, outputPath)
            if result['success']:
                self.conversationView.append(f"✅ <b>Success!</b><br>{result['message']}<hr>")
                self.populateModuleSelector()
            else:
                self.conversationView.append(f"❌ <b>Failed.</b><br>"
                                             f"<b>Final Error:</b><br><pre>{result['error']}</pre><hr>")
        except Exception as e:
            self.conversationView.append(f"❌ <b>An unexpected error occurred:</b><br><pre>{e}</pre><hr>")
            logging.error(f"DeveloperAgent unexpected error: {e}", exc_info=True)

        self.promptTextEdit.clear()
        self.sendButton.enabled = True
        self.conversationView.verticalScrollBar().setValue(self.conversationView.verticalScrollBar().maximum)

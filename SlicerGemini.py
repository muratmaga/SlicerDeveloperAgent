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
# SlicerGemini
#

class SlicerGemini(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Slicer Gemini"
        self.parent.categories = ["Developer Tools"]
        self.parent.dependencies = ["ExtensionWizard"] # Add dependency
        self.parent.contributors = ["Gemini (Google)"]
        self.parent.helpText = "This module was created by SlicerGemini."
        self.parent.acknowledgementText = "This module was developed with the assistance of Google's Gemini AI."

#
# SlicerGeminiLogic
#
class SlicerGeminiLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self._outputCallback = None

    def setOutputCallback(self, callback):
        """Set callback function to receive diagnostic output"""
        self._outputCallback = callback

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
        import google.generativeai as genai
        genai.configure(api_key=apiKey)

        if newModuleName:
            return self.createNewModule(genai, userPrompt, newModuleName, outputPath)
        elif targetModuleName:
            return self.modifyExistingModule(genai, userPrompt, targetModuleName)
        elif scriptName:
            return self.createSimpleScript(genai, userPrompt, scriptName, outputPath)
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

    def createNewModule(self, genai, userPrompt, newModuleName, outputPath=None):
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

        max_debug_attempts = 2
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

                newCode = self.call_gemini(genai, prompt_for_creation, current_code or boilerplate, error_history, "module")
                if not newCode or newCode.startswith("# Gemini API call failed"):
                    return {"success": False, "error": f"Gemini API call failed on attempt {attempt}. Check model name or API key."}

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

    def modifyExistingModule(self, genai, userPrompt, moduleName):
        modulePath = slicer.util.modulePath(moduleName)
        initialCode = self.read_code(modulePath)
        currentCode = initialCode
        errorHistory = ""
        maxAttempts = 3
        for attempt in range(maxAttempts):
            newCode = self.call_gemini(genai, userPrompt, currentCode, errorHistory, "module")
            if not newCode or newCode.startswith("# Gemini API call failed"):
                errorHistory += f"\nGemini API call failed on attempt {attempt+1}."
                continue
            self.write_code(modulePath, newCode)
            reloadResult = self.reload_and_capture(moduleName)
            if reloadResult["success"]:
                return {"success": True, "message": f"Module '{moduleName}' modified successfully."}
            errorHistory += f"\n--- Attempt {attempt + 1} Error ---\n{reloadResult['error']}"
            currentCode = newCode
        self.write_code(modulePath, initialCode)
        self.reload_and_capture(moduleName)
        return {"success": False, "error": errorHistory}

    def createSimpleScript(self, genai, userPrompt, scriptName, outputPath=None):
        """Create a simple Python script that can be executed in Slicer's Python console"""
        import traceback
        
        if outputPath:
            # Use custom output path with Scripts/ScriptName.py structure
            scripts_dir = os.path.join(outputPath, "Scripts")
            script_file_path = os.path.join(scripts_dir, f"{scriptName}.py")
        else:
            # Fallback to default directory
            settings_dir = os.path.dirname(slicer.app.slicerUserSettingsFilePath)
            scripts_dir = os.path.join(settings_dir, "SlicerGemini-Scripts")
            script_file_path = os.path.join(scripts_dir, f"{scriptName}.py")
        
        # Create scripts directory if it doesn't exist
        if not os.path.exists(scripts_dir):
            os.makedirs(scripts_dir)
        
        max_debug_attempts = 2
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
                new_code = self.call_gemini(genai, prompt_for_creation, current_code or script_template, error_history, "script")
                
                if not new_code or new_code.startswith("# Gemini API call failed"):
                    return {"success": False, "error": f"Gemini API call failed on attempt {attempt}. Check model name or API key."}

                # Write the script to file
                self.write_code(script_file_path, new_code)
                current_code = new_code
                
                # Verify the file was written correctly
                if not os.path.exists(script_file_path):
                    raise RuntimeError(f"Failed to create script file at: {script_file_path}")
                
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
                
                # If we get here, script was created and tested successfully
                result_message = f"Script '{scriptName}' created and tested successfully"
                if attempt > 0:
                    result_message += f" after {attempt} debug attempts"
                
                if outputPath:
                    result_message += f".\n\nScript structure created:\n📁 {outputPath}/\n  └── 📁 Scripts/\n      └── 📄 {scriptName}.py"
                else:
                    result_message += f". Saved to: {script_file_path}"
                
                # Try to open the script in Script Editor extension
                script_editor_result = self.openInScriptEditor(script_file_path)
                if script_editor_result["success"]:
                    result_message += f"\n\n✅ Script opened in Script Editor for editing."
                else:
                    result_message += f"\n\n⚠️ Could not open in Script Editor: {script_editor_result['error']}"
                    result_message += f"\n\nTo run this script, you can:\n1. Copy and paste the code into Slicer's Python console\n2. Use exec(open(r'{script_file_path}').read()) in the Python console\n3. Open the file in a text editor to review and modify"
                
                return {"success": True, "message": result_message}

            except Exception as e:
                error_msg = f"Error on attempt {attempt + 1}:\n{str(e)}\n{traceback.format_exc()}"
                self.diagnostic_print(f"Script creation failed:\n{error_msg}", error=True)
                error_history = error_msg
                
                if attempt == max_debug_attempts:
                    return {"success": False, "error": f"Failed to create script after {max_debug_attempts} debug attempts. Final error: {str(e)}\n\nError History:\n{error_history}"}

    def get_script_template(self, scriptName):
        """Get a basic template for a Slicer Python script"""
        return f'''"""
{scriptName} - Generated by SlicerGemini
This script implements custom functionality for 3D Slicer
"""

import slicer
import slicer.util
import logging

def main():
    """Main function that implements the script functionality"""
    try:
        # Your implementation goes here
        slicer.util.infoDisplay("Script executed successfully!")
        
    except Exception as e:
        slicer.util.errorDisplay(f"Script execution failed: {{str(e)}}")
        logging.error(f"{scriptName} execution failed: {{e}}", exc_info=True)

if __name__ == "__main__":
    main()
'''

    def testScriptExecution(self, script_code, script_name):
        """Test script execution in a safe environment"""
        try:
            self.diagnostic_print(f"Testing script '{script_name}' for basic execution errors...")
            
            # Create a controlled execution environment
            test_globals = {
                'slicer': slicer,
                'logging': logging,
                '__name__': '__main__'
            }
            
            # Try to execute the script in a more controlled way
            # First, try to compile it to catch syntax errors
            compiled_code = compile(script_code, f"<script_{script_name}>", 'exec')
            
            # Execute the compiled code
            exec(compiled_code, test_globals)
            
            self.diagnostic_print("  ✓ Script execution test completed successfully")
            return True, ""
            
        except Exception as e:
            import traceback
            error_msg = f"{script_name} execution failed: {str(e)}"
            self.diagnostic_print(f"[Python] {error_msg}")
            self.diagnostic_print(f"[Python] Traceback (most recent call last):")
            # Get the traceback and format it properly
            tb_lines = traceback.format_exc().strip().split('\n')
            for line in tb_lines[1:]:  # Skip the first line as it's redundant
                self.diagnostic_print(f"[Python] {line}")
            return False, error_msg

    def openInScriptEditor(self, script_file_path):
        """Try to open the script file in the Script Editor extension"""
        try:
            # First, verify the file exists and is readable
            if not os.path.exists(script_file_path):
                return {"success": False, "error": f"Script file does not exist: {script_file_path}"}
            
            # Check if Script Editor extension is available
            if not hasattr(slicer.modules, 'scripteditor'):
                return {"success": False, "error": "Script Editor extension is not installed or available"}
            
            # Read the file content first
            try:
                with open(script_file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                self.diagnostic_print(f"File content length: {len(file_content)} characters")
            except Exception as e:
                return {"success": False, "error": f"Cannot read script file: {str(e)}"}
            
            # Try to switch to Script Editor module
            self.diagnostic_print("Switching to Script Editor extension...")
            slicer.util.selectModule('ScriptEditor')
            
            # Wait a moment for the module to load
            slicer.app.processEvents()
            qt.QThread.msleep(2000)  # Wait for Monaco editor to load
            
            # Get the Script Editor widget
            script_editor_widget = slicer.modules.scripteditor.widgetRepresentation()
            if not script_editor_widget:
                return {"success": False, "error": "Could not access Script Editor widget"}
            
            self.diagnostic_print(f"Opening script file: {script_file_path}")
            
            # Get the actual widget implementation
            widget_self = script_editor_widget.self() if hasattr(script_editor_widget, 'self') else script_editor_widget
            
            # Method 1: Create a new text node and load the script content
            # This is the proper way to work with ScriptEditor
            try:
                self.diagnostic_print("Creating new Python text node...")
                
                # Create a new text node for the script
                script_name = os.path.splitext(os.path.basename(script_file_path))[0]
                text_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextNode')
                text_node.SetName(f"{script_name}_script")
                text_node.SetAttribute("mimetype", "text/x-python")
                text_node.SetAttribute("customTag", "pythonFile")
                text_node.SetText(file_content)
                
                # Set up storage node for saving
                storage_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTextStorageNode')
                storage_node.SetFileName(script_file_path)
                text_node.SetAndObserveStorageNodeID(storage_node.GetID())
                
                self.diagnostic_print(f"Created text node: {text_node.GetName()}")
                
                # Set this as the current node in the Script Editor
                if hasattr(widget_self, 'setCurrentNode'):
                    widget_self.setCurrentNode(text_node)
                    self.diagnostic_print("✓ Set text node as current in Script Editor")
                elif hasattr(widget_self, 'nodeComboBox'):
                    widget_self.nodeComboBox.setCurrentNode(text_node)
                    self.diagnostic_print("✓ Set text node in nodeComboBox")
                
                # Wait for the editor to update
                slicer.app.processEvents()
                qt.QThread.msleep(1000)
                
                return {"success": True, "message": f"Script opened in Script Editor as node '{text_node.GetName()}'"}
                
            except Exception as e:
                self.diagnostic_print(f"Text node approach failed: {e}")
            
            # Method 2: Try to use Monaco editor JavaScript directly
            try:
                self.diagnostic_print("Attempting direct Monaco editor approach...")
                
                if hasattr(widget_self, 'editorView') and widget_self.editorView:
                    editor_view = widget_self.editorView
                    
                    # Escape the content for JavaScript
                    escaped_content = file_content.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
                    
                    # Use JavaScript to set the editor content
                    js_code = f"if (window.editor && window.editor.getModel) {{ window.editor.getModel().setValue(`{escaped_content}`); }}"
                    
                    self.diagnostic_print("Setting content via JavaScript...")
                    editor_view.evalJS(js_code)
                    
                    # Enable the editor and buttons
                    editor_view.setEnabled(True)
                    if hasattr(widget_self, 'saveButton'):
                        widget_self.saveButton.setEnabled(True)
                    if hasattr(widget_self, 'copyButton'):
                        widget_self.copyButton.setEnabled(True)
                    
                    self.diagnostic_print("✓ Successfully set content using Monaco editor JavaScript")
                    return {"success": True, "message": "Script content loaded in Script Editor"}
                    
            except Exception as e:
                self.diagnostic_print(f"Monaco editor JavaScript approach failed: {e}")
            
            # Method 3: Try the file loader approach
            try:
                self.diagnostic_print("Attempting file loader approach...")
                
                # Use the ScriptEditor's file reader
                file_reader = None
                try:
                    from ScriptEditor import ScriptEditorFileReader
                    file_reader = ScriptEditorFileReader(None)
                    
                    properties = {'fileName': script_file_path}
                    if file_reader.load(properties):
                        self.diagnostic_print("✓ Successfully loaded using ScriptEditorFileReader")
                        return {"success": True, "message": "Script loaded using file reader"}
                        
                except ImportError:
                    self.diagnostic_print("ScriptEditorFileReader not available for direct import")
                
            except Exception as e:
                self.diagnostic_print(f"File loader approach failed: {e}")
            
            # If all methods fail, at least tell the user where the file is
            self.diagnostic_print(f"Could not automatically load file. File saved at: {script_file_path}")
            self.diagnostic_print("You can manually create a new Python text node and copy the content from the file.")
            
            return {"success": False, "error": f"Could not automatically load file in Script Editor. File saved at: {script_file_path}"}
            
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
        self.parent.contributors = ["SlicerGemini (AI)"]
        self.parent.helpText = "This module was created by SlicerGemini."

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

    def call_gemini(self, genai, prompt, code_context, error_history, request_type="module"):
        model = genai.GenerativeModel('models/gemini-pro-latest')
        
        base_prompt = """You are an expert 3D Slicer Python developer. Respond ONLY with the complete Python code, 
        no explanations or markdown. The code should be valid Python that can be directly saved to a file.
        Do not include any natural language responses or markdown code blocks.

        CRITICAL: Always use the latest Slicer API found at: https://slicer.readthedocs.io/en/latest/developer_guide/api.html
        When in doubt, refer to: https://slicer.readthedocs.io/en/latest/developer_guide/index.html
        Ignore any code examples older than two years.

        ESSENTIAL SLICER API PATTERNS TO USE:

        1. DATA LOADING:
        - Use: slicer.util.loadVolume(path) for volumes
        - Use: slicer.util.loadModel(path) for models  
        - Use: slicer.util.loadSegmentation(path) for segmentations
        - For downloads: import SampleData; SampleData.downloadFromURL(url, targetPath)
        - Alternative download: import urllib.request; urllib.request.urlretrieve(url, targetPath)

        2. NODE MANAGEMENT:
        - Get nodes: slicer.util.getNode('NodeName') or slicer.util.getFirstNodeByClass('vtkMRMLVolumeNode')
        - Create nodes: slicer.mrmlScene.AddNewNodeByClass('vtkMRMLVolumeNode')
        - Node collections: slicer.util.getNodesByClass('vtkMRMLVolumeNode')

        3. DISPLAY AND VISUALIZATION:
        - Volume rendering: slicer.modules.volumerendering.logic()
        - Layout: slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
        - 3D view: slicer.app.layoutManager().threeDWidget(0).threeDView()
        - Camera: slicer.util.resetSliceViews()

        4. UI INTERACTIONS:
        - Messages: slicer.util.infoDisplay(), slicer.util.errorDisplay(), slicer.util.warningDisplay()
        - Progress: slicer.util.showStatusMessage()
        - File dialogs: qt.QFileDialog.getOpenFileName()

        5. COMMON IMPORTS:
        - Always import: slicer, slicer.util, qt, logging
        - For modules: from slicer.ScriptedLoadableModule import *
        - For VTK: import vtk

        AVOID THESE DEPRECATED/INCORRECT PATTERNS:
        - Do NOT use: slicer.util.downloadFromURL() - this function does NOT exist
        - Do NOT use: slicer.mrmlScene.GetNodeByID() without proper error checking
        - Do NOT use: outdated volume rendering APIs
        - Do NOT use: deprecated layout constants
        - Do NOT invent methods that don't exist

        ALWAYS include proper error handling with try/except blocks and user feedback."""

        if request_type == "script":
            system_prompt = base_prompt + """
        
        SCRIPT-SPECIFIC REQUIREMENTS:
        - Create a standalone Python script that can be executed in Slicer's Python console
        - Include a main() function that contains the primary functionality
        - Use if __name__ == "__main__": main() pattern
        - Include comprehensive error handling with slicer.util.errorDisplay()
        - Provide user feedback with slicer.util.infoDisplay() for success messages
        - Structure the code for easy modification and understanding
        - Add helpful comments explaining key sections
        - CRITICAL: Avoid tuple unpacking unless you are absolutely certain about the number of return values
        - When unsure about return values, use single variable assignment and then index/attribute access
        - Always test assumptions about return values with proper error checking
        """
        else:
            system_prompt = base_prompt + """
        
        MODULE-SPECIFIC REQUIREMENTS:
        - Follow the ScriptedLoadableModule pattern with proper class inheritance
        - Include all required classes: Module, Widget, Logic
        - Implement proper setup() methods in Widget class
        - Use ScriptedLoadableModuleWidget and ScriptedLoadableModuleLogic base classes
        - Include proper module metadata (title, categories, contributors, helpText)
        - Follow Qt widget patterns for UI elements
        - Separate logic from UI in the Logic class
        """
        full_prompt = (f"{system_prompt}\n## User Request:\n{prompt}\n## Error History (if any):\n{error_history}\n"
                       f"## Code Template to Complete:\n{code_context}")
        try:
            response = model.generate_content(full_prompt)
            text_response = response.text.strip()
            
            # Clean up the response to ensure we only get valid Python code
            if text_response.startswith("```python"):
                # Extract code from markdown code block
                code = text_response[text_response.find("```python")+9:]
                code = code[:code.rfind("```")].strip()
            else:
                code = text_response
            
            # Remove any leading comments that might be explanations
            code_lines = code.split('\n')
            while code_lines and code_lines[0].strip().startswith('#'):
                code_lines.pop(0)
            
            final_code = '\n'.join(code_lines).strip() or code_context
            
            # Validate the generated code for common issues
            validation_issues = self.validateSlicerCode(final_code)
            if validation_issues:
                self.diagnostic_print(f"Code validation warnings: {'; '.join(validation_issues)}", error=True)
            
            return final_code
            
        except Exception as e:
            logging.error(f"Gemini API call failed: {e}", exc_info=True)
            return code_context  # Return original template on error

    def validateSlicerCode(self, code):
        """Validate generated code against known Slicer API patterns and common mistakes"""
        issues = []
        
        # Check for deprecated or non-existent patterns
        deprecated_patterns = [
            ("slicer.util.downloadFromURL(", "Use 'import SampleData; SampleData.downloadFromURL()' instead"),
            ("slicer.mrmlScene.GetNodeByID(", "Use slicer.util.getNode() instead"),
            ("slicer.app.layoutManager().sliceWidget(", "Use proper slice widget access"),
            ("vtk.vtkMRML", "Import specific MRML classes or use slicer.mrmlScene methods"),
            (".SetAndObserveImageData(", "Use proper volume node methods"),
        ]
        
        for pattern, suggestion in deprecated_patterns:
            if pattern in code:
                issues.append(f"Found deprecated pattern '{pattern}': {suggestion}")
        
        # Check for missing essential imports
        essential_imports = ["import slicer", "import logging"]
        for imp in essential_imports:
            if imp not in code:
                issues.append(f"Missing essential import: {imp}")
        
        # Check for proper error handling patterns
        if "try:" in code and "except:" not in code and "except " not in code:
            issues.append("Found try block without except clause")
        
        # Check for user feedback
        if "slicer.util." not in code:
            issues.append("Consider adding user feedback with slicer.util.infoDisplay() or slicer.util.errorDisplay()")
        
        # Check for potential tuple unpacking issues
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if ' = ' in stripped and (',' in stripped.split(' = ')[0]):
                # This is a tuple unpacking line
                left_side = stripped.split(' = ')[0].strip()
                comma_count = left_side.count(',')
                expected_values = comma_count + 1
                issues.append(f"Line {i}: Tuple unpacking detected expecting {expected_values} values - ensure the right side provides exactly {expected_values} values")
        
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
# SlicerGeminiWidget
#
class SlicerGeminiWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = SlicerGeminiLogic()
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
        # --- Hardcoded API Key ---
        self.apiKeyLineEdit.setText("AIzaSyAvltYg84LhCinvvxXk-eMeJg2Zt4Ffu30") # Remember to regenerate this key.
        setupFormLayout.addRow("Gemini API Key:", self.apiKeyLineEdit)
        
        # --- Output Path Configuration ---
        outputPathLayout = qt.QHBoxLayout()
        self.outputPathLineEdit = qt.QLineEdit()
        self.outputPathLineEdit.setPlaceholderText("Select output directory for generated code...")
        # Set default to Desktop
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", "SlicerGemini-Output")
        self.outputPathLineEdit.setText(desktop_path)
        self.browseOutputPathButton = qt.QPushButton("Browse...")
        self.browseOutputPathButton.clicked.connect(self.onBrowseOutputPath)
        outputPathLayout.addWidget(self.outputPathLineEdit)
        outputPathLayout.addWidget(self.browseOutputPathButton)
        setupFormLayout.addRow("Output Directory:", outputPathLayout)
        
        self.checkForGeminiLibrary()
        self.checkForScriptEditor()

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
        
        # Debug buttons
        debug_layout = qt.QHBoxLayout()
        self.debugScriptEditorButton = qt.QPushButton("🔍 Debug Script Editor")
        self.debugScriptEditorButton.clicked.connect(self.onDebugScriptEditor)
        self.debugScriptEditorButton.setStyleSheet("background-color: #f0f0f0; font-size: 10px;")
        
        self.showLastScriptButton = qt.QPushButton("📄 Show Last Generated Script")
        self.showLastScriptButton.clicked.connect(self.onShowLastScript)
        self.showLastScriptButton.setStyleSheet("background-color: #e8f4fd; font-size: 10px;")
        
        debug_layout.addWidget(self.debugScriptEditorButton)
        debug_layout.addWidget(self.showLastScriptButton)
        devFormLayout.addRow(debug_layout)

        # --- Conversation UI ---
        devFormLayout.addRow(qt.QLabel("<b>Conversation & Prompt</b>"))
        self.conversationView = qt.QTextBrowser()
        self.conversationView.setMinimumHeight(300)
        devFormLayout.addRow(self.conversationView)
        self.promptTextEdit = qt.QTextEdit()
        # --- Pre-populated Prompt ---
        self.promptTextEdit.setPlainText("Create functionality that will download data from a user specified URL and render in 3D using a single 3D view layout. Use this URL as a default URL: https://raw.githubusercontent.com/SlicerMorph/SampleData/refs/heads/master/IMPC_sample_data.nrrd\n\nIMPORTANT: To download files, use 'import SampleData' then 'SampleData.downloadFromURL(url, targetPath)'. Then use slicer.util.loadVolume(targetPath) to load it. Do NOT use slicer.util.downloadFromURL() as it doesn't exist. Use single variable assignment and proper error checking.")
        self.promptTextEdit.setFixedHeight(100)
        devFormLayout.addRow(self.promptTextEdit)
        self.sendButton = qt.QPushButton("🚀 Send Prompt to Gemini")
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

    def onDebugScriptEditor(self):
        """Debug Script Editor widget structure"""
        self.logic.debugScriptEditor()
    
    def onShowLastScript(self):
        """Show the last generated script file location and content"""
        try:
            outputPath = self.outputPathLineEdit.text.strip()
            if not outputPath:
                slicer.util.warningDisplay("No output path specified")
                return
                
            scripts_dir = os.path.join(outputPath, "Scripts")
            if not os.path.exists(scripts_dir):
                slicer.util.infoDisplay(f"No scripts directory found at: {scripts_dir}")
                return
            
            # Find the most recent script file
            script_files = []
            for file in os.listdir(scripts_dir):
                if file.endswith('.py'):
                    full_path = os.path.join(scripts_dir, file)
                    script_files.append((full_path, os.path.getmtime(full_path)))
            
            if not script_files:
                slicer.util.infoDisplay(f"No Python script files found in: {scripts_dir}")
                return
            
            # Sort by modification time and get the most recent
            script_files.sort(key=lambda x: x[1], reverse=True)
            most_recent_script = script_files[0][0]
            
            # Read and display the content
            try:
                with open(most_recent_script, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                self.conversationView.append(f"<h3>📄 Last Generated Script</h3>")
                self.conversationView.append(f"<b>File:</b> {most_recent_script}<br>")
                self.conversationView.append(f"<b>Size:</b> {len(content)} characters<br>")
                self.conversationView.append(f"<b>Content:</b><br><pre style='background-color: #f5f5f5; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto;'>{content[:2000]}{'...' if len(content) > 2000 else ''}</pre><hr>")
                
            except Exception as e:
                slicer.util.errorDisplay(f"Cannot read script file: {str(e)}")
                
        except Exception as e:
            slicer.util.errorDisplay(f"Error finding last script: {str(e)}")

    def checkForGeminiLibrary(self):
        try:
            import google.generativeai
        except ImportError:
            self.showInstallMessage()

    def checkForScriptEditor(self):
        """Check if Script Editor extension is available"""
        if not hasattr(slicer.modules, 'scripteditor'):
            self.conversationView.append(
                "<div style='background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 10px; margin: 5px 0; border-radius: 5px;'>"
                "<b>📝 Script Editor Extension</b><br>"
                "For the best script editing experience, consider installing the Script Editor extension:<br>"
                "• Go to Extensions Manager → Install Extensions<br>"
                "• Search for 'Script Editor' by SlicerMorph<br>"
                "• Or visit: <a href='https://github.com/SlicerMorph/SlicerScriptEditor'>https://github.com/SlicerMorph/SlicerScriptEditor</a><br>"
                "Generated scripts will automatically open in Script Editor when available."
                "</div>"
            )

    def showInstallMessage(self):
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("Google AI Library Not Found")
        msg.setInformativeText("The 'google-generativeai' library is required. Would you like to install it now?")
        msg.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
        if msg.exec_() == qt.QMessageBox.Ok:
            self.conversationView.append("<b>Installing 'google-generativeai'...</b>")
            slicer.util.pip_install('google-generativeai')
            self.conversationView.append("<b>Installation complete.</b>")

    def populateModuleSelector(self):
        self.targetModuleSelector.clear()
        self.targetModuleSelector.addItem("", None)
        moduleNames = slicer.app.moduleManager().modulesNames()
        scriptedModuleNames = []
        for name in moduleNames:
            if name == "SlicerGemini":
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
            slicer.util.warningDisplay("Please enter your Gemini API Key.")
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
            logging.error(f"SlicerGemini unexpected error: {e}", exc_info=True)

        self.promptTextEdit.clear()
        self.sendButton.enabled = True
        self.conversationView.verticalScrollBar().setValue(self.conversationView.verticalScrollBar().maximum)

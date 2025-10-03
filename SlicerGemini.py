import os
import sys
import logging
import contextlib
from io import StringIO

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

    def processRequest(self, apiKey, userPrompt, newModuleName=None, targetModuleName=None):
        import google.generativeai as genai
        genai.configure(api_key=apiKey)

        if newModuleName:
            return self.createNewModule(genai, userPrompt, newModuleName)
        elif targetModuleName:
            return self.modifyExistingModule(genai, userPrompt, targetModuleName)
        return {"success": False, "error": "No target or new module name specified."}

    def createNewModule(self, genai, userPrompt, newModuleName):
        boilerplate = self.get_module_boilerplate(newModuleName)
        prompt_for_creation = (
            f"Create a complete 3D Slicer module named '{newModuleName}' that implements the following functionality: {userPrompt}. "
            f"Return ONLY the complete Python code without any explanation or markdown formatting. The code must be valid Python syntax."
        )
        try:
            newCode = self.call_gemini(genai, prompt_for_creation, boilerplate, "")
            if not newCode or newCode.startswith("# Gemini API call failed"):
                 return {"success": False, "error": "Gemini API call failed. Check model name or API key."}

            settings_dir = os.path.dirname(slicer.app.slicerUserSettingsFilePath)
            # Create a proper module directory structure
            moduleTopLevelDir = os.path.join(settings_dir, "qt-scripted-modules", newModuleName)
            if not os.path.exists(moduleTopLevelDir):
                os.makedirs(moduleTopLevelDir)

            filePath = os.path.join(moduleTopLevelDir, f"{newModuleName}.py")
            self.write_code(filePath, newCode)

            # Add module to the Python path if needed
            if moduleTopLevelDir not in sys.path:
                sys.path.append(moduleTopLevelDir)
            
            # Ensure the module factory is updated
            factory = slicer.app.moduleManager().factoryManager()
            factory.registerModule(qt.QFileInfo(filePath))
            factory.loadModules([newModuleName])
            
            # Select the module to show it
            slicer.util.selectModule(newModuleName)

            return {"success": True, "message": f"Module '{newModuleName}' created and loaded. It is saved in: {moduleTopLevelDir}"}
        except Exception as e:
            logging.error(f"Failed to create new module: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def modifyExistingModule(self, genai, userPrompt, moduleName):
        modulePath = slicer.util.modulePath(moduleName)
        initialCode = self.read_code(modulePath)
        currentCode = initialCode
        errorHistory = ""
        maxAttempts = 3
        for attempt in range(maxAttempts):
            newCode = self.call_gemini(genai, userPrompt, currentCode, errorHistory)
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

    def call_gemini(self, genai, prompt, code_context, error_history):
        model = genai.GenerativeModel('models/gemini-pro-latest')
        system_prompt = """You are an expert 3D Slicer Python developer. Respond ONLY with the complete Python code, 
        no explanations or markdown. The code should be valid Python that can be directly saved to a file.
        Do not include any natural language responses or markdown code blocks."""
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
            
            return '\n'.join(code_lines).strip() or code_context
            
        except Exception as e:
            logging.error(f"Gemini API call failed: {e}", exc_info=True)
            return code_context  # Return original template on error

    def reload_and_capture(self, module_name):
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
        self.apiKeyLineEdit.setText("") # Remember to regenerate this key.
        setupFormLayout.addRow("Gemini API Key:", self.apiKeyLineEdit)
        self.checkForGeminiLibrary()

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

        # --- Conversation UI ---
        devFormLayout.addRow(qt.QLabel("<b>Conversation & Prompt</b>"))
        self.conversationView = qt.QTextBrowser()
        self.conversationView.setMinimumHeight(300)
        devFormLayout.addRow(self.conversationView)
        self.promptTextEdit = qt.QTextEdit()
        # --- Pre-populated Prompt ---
        self.promptTextEdit.setPlainText("Create a new module that will download data from a user specified URL and render in 3D using a single 3D view layout.")
        self.promptTextEdit.setFixedHeight(100)
        devFormLayout.addRow(self.promptTextEdit)
        self.sendButton = qt.QPushButton("🚀 Send Prompt to Gemini")
        devFormLayout.addRow(self.sendButton)

        # Connections
        self.sendButton.clicked.connect(self.onSendPromptButtonClicked)
        self.newModuleNameLineEdit.textChanged.connect(self.onNewModuleNameChanged)
        self.targetModuleSelector.currentIndexChanged.connect(self.onTargetModuleChanged)

        self.layout.addStretch(1)

    def onNewModuleNameChanged(self, text):
        self.targetModuleSelector.enabled = not bool(text)

    def onTargetModuleChanged(self, index):
        self.newModuleNameLineEdit.enabled = index <= 0

    def checkForGeminiLibrary(self):
        try:
            import google.generativeai
        except ImportError:
            self.showInstallMessage()

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

        if not apiKey:
            slicer.util.warningDisplay("Please enter your Gemini API Key.")
            return
        if not userPrompt:
            slicer.util.warningDisplay("Please enter a development prompt.")
            return
        if not newModuleName and not targetModuleName:
            slicer.util.warningDisplay("Please either enter a 'New Module Name' or select a 'Target Module'.")
            return

        self.sendButton.enabled = False
        display_target = newModuleName if newModuleName else targetModuleName
        self.conversationView.append(f"<h2>New Request</h2><b>{'Creating' if newModuleName else 'Modifying'} Module:</b> {display_target}<br>"
                                     f"<b>Prompt:</b> {userPrompt}<br>"
                                     f"<i>Processing, please wait...</i><hr>")
        slicer.app.processEvents()

        try:
            result = self.logic.processRequest(apiKey, userPrompt, newModuleName, targetModuleName)
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
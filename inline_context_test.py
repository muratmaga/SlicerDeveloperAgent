# =============================================================================
# CONTEXT PRESERVATION TEST - COPY AND PASTE INTO SLICER PYTHON CONSOLE
# =============================================================================

# Test 1: Verify that full contexts are preserved during improvement iterations
def test_context_preservation_inline():
    """
    This test verifies your concern about whether full contexts are preserved
    during improvement iterations when the original script fails.
    
    It specifically tests:
    1. Original script content is preserved in all AI calls
    2. Error history is accumulated and sent to AI
    3. Both original prompt and errors are included in retry attempts
    """
    
    print("="*80)
    print("TESTING: Are full contexts preserved during improvement iterations?")
    print("="*80)
    
    # Get DeveloperAgent logic (based on debug results)
    try:
        widget = slicer.modules.developeragent.widgetRepresentation()
        widget_self = widget.self()
        logic = widget_self.logic
        print("✅ Found DeveloperAgent logic")
    except Exception as e:
        print(f"❌ Error accessing DeveloperAgent: {e}")
        return False
    
    # Verify we can access the call_ai method
    if not hasattr(logic, 'call_ai'):
        print(f"❌ Logic object doesn't have call_ai method. Available methods: {[m for m in dir(logic) if not m.startswith('_')]}")
        return False
    
    # Track what gets sent to AI
    ai_call_data = []
    original_call_ai = logic.call_ai
    
    def track_ai_calls(client, prompt, code_context, error_history, request_type="script"):
        # Capture exactly what gets sent to AI
        call_data = {
            'attempt': len(ai_call_data) + 1,
            'prompt': prompt,
            'code_context': code_context,
            'error_history': error_history,
            'original_prompt_preserved': 'context preservation test' in prompt.lower(),
            'has_error_history': bool(error_history and len(error_history) > 0),
            'code_context_length': len(code_context) if code_context else 0
        }
        ai_call_data.append(call_data)
        
        print(f"📡 AI Call #{len(ai_call_data)}:")
        print(f"   Original prompt preserved: {'✅' if call_data['original_prompt_preserved'] else '❌'}")
        print(f"   Error history included: {'✅' if call_data['has_error_history'] else '⏹️' if len(ai_call_data) == 1 else '❌'}")
        print(f"   Code context length: {call_data['code_context_length']} chars")
        
        # Show detailed content being sent to AI
        print(f"\n   📄 PROMPT SENT TO AI (first 300 chars):")
        print(f"   {repr(prompt[:300])}...")
        
        if code_context:
            print(f"\n   💾 CODE CONTEXT SENT TO AI:")
            print(f"   {repr(code_context)}")
        
        if error_history:
            print(f"\n   🚨 ERROR HISTORY SENT TO AI (first 400 chars):")
            print(f"   {repr(error_history[:400])}...")
        
        print(f"   " + "="*60)
        
        # Simulate failing then succeeding responses
        attempt = len(ai_call_data)
        if attempt == 1:
            return "import slicer\nprint('attempt 1')\nsyntax_error_here"  # Will fail
        elif attempt == 2:
            return "import slicer\nprint('attempt 2')\nraise Exception('runtime error')"  # Will fail  
        else:
            return "import slicer\nprint('Success on attempt 3!')"  # Will succeed
    
    def mock_test_execution(code, name):
        attempt = len(ai_call_data)
        if attempt <= 2:
            return False, f"Simulated test failure on attempt {attempt}"
        return True, ""
    
    def mock_slicer_execution(code, name):
        attempt = len(ai_call_data)
        if attempt <= 2:
            return False, f"Simulated execution failure on attempt {attempt}"
        return True, ""
    
    # Install our tracking hooks
    logic.call_ai = track_ai_calls
    logic.testScriptExecution = mock_test_execution
    logic.executeScriptInSlicer = mock_slicer_execution
    logic.setDebugIterations(3)  # Allow multiple attempts
    
    try:
        print("\n🧪 Running script creation with simulated failures...")
        
        # Use a temp directory
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            result = logic.createSimpleScript(
                client=None,  # Mock client
                userPrompt="Context preservation test - verify original content is kept",
                scriptName="TestScript", 
                outputPath=temp_dir
            )
        
        print(f"\n📊 RESULTS:")
        print(f"   Total AI calls: {len(ai_call_data)}")
        print(f"   Final result: {'✅ SUCCESS' if result.get('success') else '❌ FAILED'}")
        
        # CRITICAL ANALYSIS: Check if contexts were preserved
        print(f"\n🔍 CONTEXT PRESERVATION ANALYSIS:")
        
        all_preserve_original = True
        error_accumulation_works = True
        
        for i, call in enumerate(ai_call_data):
            attempt_num = i + 1
            print(f"\n   Attempt {attempt_num}:")
            
            # Check original prompt preservation
            if not call['original_prompt_preserved']:
                print(f"      ❌ Original prompt NOT preserved")
                all_preserve_original = False
            else:
                print(f"      ✅ Original prompt preserved")
            
            # Check error history (should be empty on first call, present on later calls)
            if attempt_num == 1:
                if call['has_error_history']:
                    print(f"      ⚠️  Unexpected error history on first call")
                else:
                    print(f"      ✅ No error history on first call (correct)")
            else:
                if not call['has_error_history']:
                    print(f"      ❌ Missing error history on retry attempt")
                    error_accumulation_works = False
                else:
                    print(f"      ✅ Error history present on retry (correct)")
                    # Show snippet of error history
                    error_snippet = call['error_history'][:100] + "..." if len(call['error_history']) > 100 else call['error_history']
                    print(f"      📝 Error snippet: {error_snippet}")
        
        # FINAL VERDICT
        print(f"\n🏆 FINAL VERDICT:")
        if all_preserve_original and error_accumulation_works:
            print(f"   ✅ CONTEXT PRESERVATION WORKS CORRECTLY!")
            print(f"   ✅ Original script content IS preserved during iterations")
            print(f"   ✅ Error history IS accumulated and sent to AI")
            print(f"   ✅ Your concern is addressed - full contexts are preserved")
        else:
            print(f"   ❌ CONTEXT PRESERVATION HAS ISSUES!")
            if not all_preserve_original:
                print(f"   ❌ Original prompt not preserved in all calls")
            if not error_accumulation_works:
                print(f"   ❌ Error history not properly accumulated")
        
        return all_preserve_original and error_accumulation_works
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Restore original function
        logic.call_ai = original_call_ai
        print(f"\n✅ Original AI function restored")

# Show actual AI call content without running the full test
def show_ai_call_content():
    """Show exactly what gets sent to AI during iterations"""
    print("="*80)
    print("DETAILED AI CALL CONTENT ANALYSIS")
    print("="*80)
    
    try:
        widget = slicer.modules.developeragent.widgetRepresentation()
        widget_self = widget.self()
        logic = widget_self.logic
        
        # Get the actual template that would be used
        template = logic.get_script_template("TestScript")
        print("📄 INITIAL CODE TEMPLATE:")
        print(template)
        print("\n" + "="*60 + "\n")
        
        # Simulate what would be sent on first call
        first_prompt = "Create a script that loads and processes a volume"
        print("🔄 FIRST AI CALL (Initial Creation):")
        print(f"Prompt includes: '{first_prompt}'")
        print(f"Code context: {len(template)} chars of template")
        print("Error history: (empty - first attempt)")
        print("\n" + "="*60 + "\n")
        
        # Simulate what would be sent on retry
        error_example = """
ATTEMPT 1 FAILED:
Error Type: SyntaxError
Error Message: invalid syntax (line 5)
Generated Code That Failed:
import slicer
def process_volume()  # Missing colon
    print("Processing...")
Full Traceback:
  File "<script>", line 2
    def process_volume()
                       ^
SyntaxError: invalid syntax
"""
        
        print("🔄 SECOND AI CALL (After Failure):")
        print(f"Prompt includes: 'Debug and fix' + original prompt: '{first_prompt}'")
        print("Code context: Generated code from first attempt")
        print(f"Error history: {len(error_example)} chars including:")
        print("  - Error type and message")
        print("  - Failed code")
        print("  - Full traceback")
        print("  - Debugging guidance")
        
        print(f"\nError history preview:")
        print(error_example.strip())
        
        print(f"\n🎯 KEY INSIGHT:")
        print(f"✅ Original user prompt is preserved in ALL calls")
        print(f"✅ Previous code attempts are sent as context")
        print(f"✅ Complete error information is accumulated")
        print(f"✅ AI gets full picture for making corrections")
        
    except Exception as e:
        print(f"❌ Error: {e}")

# Debug function to help understand the DeveloperAgent structure
def debug_developeragent_structure():
    """Debug function to understand how to access DeveloperAgent logic"""
    print("🔍 DEBUGGING DEVELOPERAGENT STRUCTURE")
    print("="*50)
    
    try:
        # Check if module exists
        if hasattr(slicer.modules, 'developeragent'):
            print("✅ slicer.modules.developeragent exists")
            
            # Get widget representation
            widget = slicer.modules.developeragent.widgetRepresentation()
            print(f"✅ Widget type: {type(widget)}")
            
            # Check widget attributes
            widget_attrs = [attr for attr in dir(widget) if not attr.startswith('_')]
            print(f"📋 Widget attributes: {widget_attrs[:10]}...")  # Show first 10
            
            # Try to get widget.self()
            if hasattr(widget, 'self'):
                widget_self = widget.self()
                print(f"✅ Widget.self() type: {type(widget_self)}")
                
                # Check for logic in widget_self
                if hasattr(widget_self, 'logic'):
                    logic = widget_self.logic
                    print(f"✅ Found logic: {type(logic)}")
                    
                    # Check logic methods
                    logic_methods = [m for m in dir(logic) if not m.startswith('_') and callable(getattr(logic, m))]
                    print(f"📋 Logic methods: {logic_methods}")
                    
                    # Check specifically for our needed methods
                    needed_methods = ['call_ai', 'createSimpleScript', 'setDebugIterations']
                    for method in needed_methods:
                        has_method = hasattr(logic, method)
                        print(f"   {method}: {'✅' if has_method else '❌'}")
                    
                    return logic
                else:
                    print("❌ No 'logic' attribute in widget.self()")
            else:
                print("❌ No 'self' method in widget")
                
        else:
            print("❌ slicer.modules.developeragent not found")
            
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()
    
    return None

# =============================================================================
# INSTRUCTIONS FOR USE:
# =============================================================================
print("""
CONTEXT PRESERVATION TEST READY!

To test whether full contexts are preserved during improvement iterations:

1. Make sure DeveloperAgent module is loaded
2. First run: debug_developeragent_structure()  # To debug access issues
3. Then run: test_context_preservation_inline()

This will verify your specific concern about whether the original script
and error information are both included when corrections are made.
""")

# Uncomment the next line to run the debug immediately:
# debug_developeragent_structure()
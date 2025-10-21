"""
SIMPLE CONTEXT PRESERVATION TEST FOR SLICER PYTHON CONSOLE

Copy and paste this entire script into Slicer's Python console to test
whether full contexts are preserved during improvement iterations.
"""

# Test whether context preservation works correctly
def test_context_preservation_simple():
    print("="*80)
    print("TESTING CONTEXT PRESERVATION IN DEVELOPER AGENT")
    print("="*80)
    
    # Get the DeveloperAgent logic
    try:
        logic = slicer.modules.developeragent.logic
        print("✅ DeveloperAgent logic found")
    except:
        print("❌ DeveloperAgent not found. Please load the DeveloperAgent module first.")
        return False
    
    # Create a mock client and track AI calls
    class MockClient:
        pass
    
    mock_client = MockClient()
    ai_calls = []
    original_call_ai = logic.call_ai
    
    def mock_call_ai(client, prompt, code_context, error_history, request_type="script"):
        call_info = {
            'call_number': len(ai_calls) + 1,
            'prompt_length': len(prompt),
            'code_context_length': len(code_context) if code_context else 0,
            'error_history_length': len(error_history) if error_history else 0,
            'has_original_prompt': 'test context preservation' in prompt.lower(),
            'has_error_history': len(error_history) > 0 if error_history else False
        }
        ai_calls.append(call_info)
        
        # Simulate different responses for each call
        if len(ai_calls) == 1:
            return "import slicer\nprint('First attempt')\nundefined_variable_error"  # Syntax error
        elif len(ai_calls) == 2:
            return "import slicer\nprint('Second attempt')\nraise RuntimeError('Simulated runtime error')"  # Runtime error
        else:
            return "import slicer\nprint('Third attempt - success!')"  # Success
    
    def mock_test_execution(code, name):
        if len(ai_calls) <= 2:
            return False, f"Simulated error for attempt {len(ai_calls)}"
        return True, ""
    
    def mock_slicer_execution(code, name):
        if len(ai_calls) <= 2:
            return False, f"Simulated Slicer execution error for attempt {len(ai_calls)}"
        return True, ""
    
    # Replace methods with mocks
    logic.call_ai = mock_call_ai
    logic.testScriptExecution = mock_test_execution
    logic.executeScriptInSlicer = mock_slicer_execution
    
    try:
        print("Starting test with 3 debug iterations...")
        logic.setDebugIterations(3)
        
        # Create a temporary directory for testing
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as temp_dir:
            result = logic.createSimpleScript(
                client=mock_client,
                userPrompt="Test context preservation functionality",
                scriptName="ContextPreservationTest",
                outputPath=temp_dir
            )
        
        print(f"\nTest completed. Result: {'SUCCESS' if result['success'] else 'FAILED'}")
        print(f"Total AI calls made: {len(ai_calls)}")
        
        # Analyze results
        print("\n" + "="*60)
        print("CONTEXT PRESERVATION ANALYSIS")
        print("="*60)
        
        for i, call in enumerate(ai_calls, 1):
            print(f"\nCALL {i}:")
            print(f"  Prompt length: {call['prompt_length']} chars")
            print(f"  Code context length: {call['code_context_length']} chars") 
            print(f"  Error history length: {call['error_history_length']} chars")
            print(f"  Has original prompt: {'✅' if call['has_original_prompt'] else '❌'}")
            print(f"  Has error history: {'✅' if call['has_error_history'] else '❌' if i > 1 else '⏹️ (expected)'}")
        
        # Verification
        print("\n" + "="*60)
        print("VERIFICATION RESULTS")
        print("="*60)
        
        all_calls_have_original = all(call['has_original_prompt'] for call in ai_calls)
        later_calls_have_errors = all(call['has_error_history'] for call in ai_calls[1:]) if len(ai_calls) > 1 else True
        context_increases = all(ai_calls[i]['code_context_length'] > 0 for i in range(len(ai_calls)))
        
        print(f"✅ Original prompt preserved in all calls: {all_calls_have_original}")
        print(f"✅ Error history present in retry calls: {later_calls_have_errors}")
        print(f"✅ Code context provided in all calls: {context_increases}")
        
        if all_calls_have_original and later_calls_have_errors and context_increases:
            print(f"\n🎉 CONTEXT PRESERVATION TEST PASSED!")
            print("✅ Full contexts ARE preserved during improvement iterations")
            print("✅ Original script content is maintained")
            print("✅ Error history is accumulated properly")
            success = True
        else:
            print(f"\n❌ CONTEXT PRESERVATION TEST FAILED!")
            print("❌ Context preservation has issues")
            success = False
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    finally:
        # Restore original methods
        logic.call_ai = original_call_ai
    
    print("="*80)
    return success

# Run the test
print("Context Preservation Test Script Loaded")
print("Run: test_context_preservation_simple()")
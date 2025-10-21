"""
Test Context Preservation During Improvement Iterations - Slicer Version

This test verifies that when a script fails during improvement iterations,
both the original script content and error information are preserved and
sent to the AI for correction.

The test simulates various failure scenarios and checks:
1. Original script content is preserved
2. Error history is accumulated properly  
3. Full context (original + errors) is sent to AI
4. Multiple iteration cycles preserve all information

Usage in Slicer Python Console:
exec(open('/path/to/test_context_preservation.py').read())
"""

# Import required modules that are available in Slicer
import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO
import traceback

# Import Slicer modules - these should be available in Slicer environment
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import qt
import ctk

# Import the DeveloperAgent logic from the loaded module
from DeveloperAgent import DeveloperAgentLogic

class TestContextPreservation(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.logic = DeveloperAgentLogic()
        self.logic.setDebugIterations(3)  # Set to 3 for thorough testing
        
        # Mock client for AI calls
        self.mock_client = Mock()
        
        # Store AI call history for verification
        self.ai_call_history = []
        
        # Create a mock AI response function that simulates failures then success
        self.call_count = 0
        self.original_call_ai = self.logic.call_ai
        
    def tearDown(self):
        """Clean up after tests"""
        # Restore original method if it was patched
        if hasattr(self, 'original_call_ai'):
            self.logic.call_ai = self.original_call_ai
            
    def mock_call_ai_with_tracking(self, client, prompt, code_context, error_history, request_type="script"):
        """Mock call_ai that tracks all parameters and simulates realistic failures"""
        self.call_count += 1
        
        # Store the call details for later verification
        call_details = {
            'call_number': self.call_count,
            'prompt': prompt,
            'code_context': code_context,
            'error_history': error_history,
            'request_type': request_type,
            'code_context_length': len(code_context) if code_context else 0,
            'error_history_length': len(error_history) if error_history else 0
        }
        self.ai_call_history.append(call_details)
        
        # Simulate different failure scenarios based on call count
        if self.call_count == 1:
            # First call: Generate code with a syntax error
            return '''
import slicer
import slicer.util

# This code has a deliberate syntax error
def process_data()
    print("Missing colon in function definition")
    volume = slicer.util.loadVolume("test.nrrd")
    return volume
    
process_data()
'''
        elif self.call_count == 2:
            # Second call: Generate code with a runtime error
            return '''
import slicer
import slicer.util

def process_data():
    print("Processing data...")
    # This will cause a runtime error - undefined variable
    volume = slicer.util.loadVolume(undefined_file_path)
    return volume
    
process_data()
'''
        elif self.call_count == 3:
            # Third call: Generate working code
            return '''
import slicer
import slicer.util

def process_data():
    print("Processing data successfully...")
    # This should work (in a real Slicer environment)
    try:
        volume = slicer.util.loadVolume("https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/MRHead.nrrd")
        if volume:
            print(f"Loaded volume: {volume.GetName()}")
        return volume
    except Exception as e:
        print(f"Could not load volume: {e}")
        return None
    
result = process_data()
print("Script completed")
'''
        else:
            # Fallback for additional calls
            return "print('Fallback script')"
    
    def mock_failing_script_execution(self, script_code, script_name):
        """Mock script execution that fails for the first two attempts"""
        if self.call_count <= 2:
            if self.call_count == 1:
                return False, "SyntaxError: invalid syntax (line 5)\ndef process_data()\n              ^\nSyntaxError: invalid syntax"
            elif self.call_count == 2:
                return False, "NameError: name 'undefined_file_path' is not defined"
        else:
            return True, ""  # Success on third attempt
            
    def mock_failing_slicer_execution(self, script_code, script_name):
        """Mock Slicer execution that fails for the first two attempts"""
        if self.call_count <= 2:
            if self.call_count == 1:
                return False, "Failed to execute script in Slicer: SyntaxError: invalid syntax"
            elif self.call_count == 2:
                return False, "Failed to execute script in Slicer: NameError: name 'undefined_file_path' is not defined"
        else:
            return True, ""  # Success on third attempt

    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_context_preservation_in_script_creation(self, mock_makedirs, mock_exists):
        """Test that context is preserved during script creation with failures"""
        
        # Setup mocks
        mock_exists.return_value = True
        mock_makedirs.return_value = None
        
        # Replace methods with our tracking mocks
        self.logic.call_ai = self.mock_call_ai_with_tracking
        self.logic.testScriptExecution = self.mock_failing_script_execution
        self.logic.executeScriptInSlicer = self.mock_failing_slicer_execution
        
        # Mock file writing
        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            
            # Run the test
            result = self.logic.createSimpleScript(
                client=self.mock_client,
                userPrompt="Create a script that loads and processes a volume",
                scriptName="TestScript",
                outputPath="/test/output"
            )
        
        # Verify the test ran through all iterations
        self.assertEqual(len(self.ai_call_history), 3, "Expected 3 AI calls for 2 debug attempts + 1 initial")
        
        # Test 1: Verify first call has initial context
        first_call = self.ai_call_history[0]
        self.assertEqual(first_call['call_number'], 1)
        self.assertIn("Create a script that loads and processes a volume", first_call['prompt'])
        self.assertGreater(first_call['code_context_length'], 0, "First call should have template context")
        self.assertEqual(first_call['error_history_length'], 0, "First call should have no error history")
        
        # Test 2: Verify second call preserves context AND adds error history
        second_call = self.ai_call_history[1]
        self.assertEqual(second_call['call_number'], 2)
        self.assertIn("Debug and fix", second_call['prompt'])
        self.assertIn("Create a script that loads and processes a volume", second_call['prompt'])
        self.assertGreater(second_call['code_context_length'], 0, "Second call should preserve generated code context")
        self.assertGreater(second_call['error_history_length'], 0, "Second call should have error history")
        self.assertIn("SyntaxError", second_call['error_history'])
        
        # Test 3: Verify third call preserves ALL previous context
        third_call = self.ai_call_history[2]
        self.assertEqual(third_call['call_number'], 3)
        self.assertIn("Debug and fix", third_call['prompt'])
        self.assertIn("Create a script that loads and processes a volume", third_call['prompt'])
        self.assertGreater(third_call['code_context_length'], 0, "Third call should preserve updated code context")
        self.assertGreater(third_call['error_history_length'], 0, "Third call should have accumulated error history")
        
        # Test 4: Verify error history accumulation
        # The third call should contain errors from BOTH previous attempts
        self.assertIn("ATTEMPT 1 FAILED", third_call['error_history'])
        self.assertIn("ATTEMPT 2 FAILED", third_call['error_history'])
        self.assertIn("SyntaxError", third_call['error_history'])
        self.assertIn("NameError", third_call['error_history'])
        
        # Test 5: Verify that original prompt is preserved through all iterations
        for call in self.ai_call_history:
            self.assertIn("Create a script that loads and processes a volume", call['prompt'],
                         f"Original prompt should be preserved in call {call['call_number']}")
        
        # Test 6: Verify success after iterations
        self.assertTrue(result['success'], f"Script creation should succeed after iterations. Error: {result.get('error', 'No error')}")
        
        print("\n" + "="*80)
        print("CONTEXT PRESERVATION TEST RESULTS")
        print("="*80)
        
        for i, call in enumerate(self.ai_call_history, 1):
            print(f"\n--- CALL {i} ---")
            print(f"Prompt length: {len(call['prompt'])} chars")
            print(f"Code context length: {call['code_context_length']} chars")
            print(f"Error history length: {call['error_history_length']} chars")
            print(f"Has original prompt: {'✓' if 'Create a script that loads and processes a volume' in call['prompt'] else '✗'}")
            if call['error_history_length'] > 0:
                error_preview = call['error_history'][:200] + "..." if len(call['error_history']) > 200 else call['error_history']
                print(f"Error history preview: {error_preview}")

    def test_error_history_accumulation_format(self):
        """Test that error history is properly formatted and accumulated"""
        
        # Setup mocks
        self.logic.call_ai = self.mock_call_ai_with_tracking
        self.logic.testScriptExecution = self.mock_failing_script_execution
        self.logic.executeScriptInSlicer = self.mock_failing_slicer_execution
        
        with patch('os.path.exists', return_value=True), \
             patch('os.makedirs'), \
             patch('builtins.open', create=True):
            
            # Run the test
            result = self.logic.createSimpleScript(
                client=self.mock_client,
                userPrompt="Test error accumulation",
                scriptName="TestScript",
                outputPath="/test/output"
            )
        
        # Verify error history format in the final call
        final_call = self.ai_call_history[-1]
        error_history = final_call['error_history']
        
        # Test that error history contains structured information
        self.assertIn("ATTEMPT 1 FAILED:", error_history)
        self.assertIn("ATTEMPT 2 FAILED:", error_history)
        self.assertIn("Error Type:", error_history)
        self.assertIn("Error Message:", error_history)
        self.assertIn("Generated Code That Failed:", error_history)
        self.assertIn("Full Traceback:", error_history)
        self.assertIn("DEBUGGING GUIDANCE:", error_history)
        
        print("\n" + "="*80)
        print("ERROR HISTORY FORMAT TEST")
        print("="*80)
        print(f"Final error history length: {len(error_history)} chars")
        print(f"Contains structured format: ✓")
        print(f"Contains debugging guidance: ✓")

    def test_original_script_preservation_on_failure(self):
        """Test that when all attempts fail, the original context is still preserved"""
        
        # Create a mock that always fails
        def always_fail_call_ai(client, prompt, code_context, error_history, request_type="script"):
            self.call_count += 1
            call_details = {
                'call_number': self.call_count,
                'prompt': prompt,
                'code_context': code_context,
                'error_history': error_history,
                'request_type': request_type
            }
            self.ai_call_history.append(call_details)
            
            return f"# Failing script attempt {self.call_count}\nprint('This will fail')\nundefined_function_call()"
        
        def always_fail_execution(script_code, script_name):
            return False, f"Simulated failure {self.call_count}"
        
        # Setup mocks
        self.logic.call_ai = always_fail_call_ai
        self.logic.testScriptExecution = always_fail_execution
        self.logic.executeScriptInSlicer = always_fail_execution
        
        with patch('os.path.exists', return_value=True), \
             patch('os.makedirs'), \
             patch('builtins.open', create=True):
            
            # Run the test - should fail after max attempts
            result = self.logic.createSimpleScript(
                client=self.mock_client,
                userPrompt="Original task that should be preserved",
                scriptName="FailingScript",
                outputPath="/test/output"
            )
        
        # Verify failure but context preservation
        self.assertFalse(result['success'], "Script should fail after max attempts")
        self.assertEqual(len(self.ai_call_history), 4, "Should have made 4 attempts (1 initial + 3 debug)")
        
        # Verify original prompt is preserved in ALL calls, even final failure
        for call in self.ai_call_history:
            self.assertIn("Original task that should be preserved", call['prompt'],
                         f"Original prompt missing in call {call['call_number']}")
        
        # Verify final call has accumulated ALL previous errors
        final_call = self.ai_call_history[-1]
        for i in range(1, 4):  # Should have errors from attempts 1-3
            self.assertIn(f"ATTEMPT {i} FAILED", final_call['error_history'],
                         f"Missing error from attempt {i} in final call")
        
        print("\n" + "="*80)
        print("FAILURE CONTEXT PRESERVATION TEST")
        print("="*80)
        print(f"Total attempts: {len(self.ai_call_history)}")
        print(f"All calls preserve original prompt: ✓")
        print(f"Final call has all error history: ✓")
        print(f"Test result: {'PASS' if not result['success'] else 'UNEXPECTED SUCCESS'}")

    def test_code_context_evolution(self):
        """Test that code context evolves properly through iterations"""
        
        self.logic.call_ai = self.mock_call_ai_with_tracking
        self.logic.testScriptExecution = self.mock_failing_script_execution
        self.logic.executeScriptInSlicer = self.mock_failing_slicer_execution
        
        with patch('os.path.exists', return_value=True), \
             patch('os.makedirs'), \
             patch('builtins.open', create=True):
            
            result = self.logic.createSimpleScript(
                client=self.mock_client,
                userPrompt="Test code evolution",
                scriptName="EvolutionTest",
                outputPath="/test/output"
            )
        
        # Verify code context changes between calls
        first_context = self.ai_call_history[0]['code_context']
        second_context = self.ai_call_history[1]['code_context']
        third_context = self.ai_call_history[2]['code_context']
        
        # First call should have template, subsequent calls should have generated code
        self.assertIn("Your implementation goes here", first_context)  # Template content
        self.assertIn("def process_data()", second_context)  # Generated code from first call
        self.assertIn("undefined_file_path", third_context)  # Generated code from second call
        
        print("\n" + "="*80)
        print("CODE CONTEXT EVOLUTION TEST")
        print("="*80)
        print(f"First context length: {len(first_context)} chars (template)")
        print(f"Second context length: {len(second_context)} chars (generated code)")
        print(f"Third context length: {len(third_context)} chars (updated code)")
        print("Code context evolves properly: ✓")

    def test_diagnostic_output_preservation(self):
        """Test that diagnostic output is properly captured and preserved"""
        
        diagnostic_messages = []
        
        def capture_diagnostic(message, error=False):
            diagnostic_messages.append({
                'message': message,
                'error': error,
                'call_count': self.call_count
            })
        
        self.logic.diagnostic_print = capture_diagnostic
        self.logic.call_ai = self.mock_call_ai_with_tracking
        self.logic.testScriptExecution = self.mock_failing_script_execution
        self.logic.executeScriptInSlicer = self.mock_failing_slicer_execution
        
        with patch('os.path.exists', return_value=True), \
             patch('os.makedirs'), \
             patch('builtins.open', create=True):
            
            result = self.logic.createSimpleScript(
                client=self.mock_client,
                userPrompt="Test diagnostic preservation",
                scriptName="DiagnosticTest",
                outputPath="/test/output"
            )
        
        # Verify diagnostic messages were captured
        self.assertGreater(len(diagnostic_messages), 0, "Should have diagnostic messages")
        
        # Look for key diagnostic patterns
        has_attempt_messages = any("Attempt" in msg['message'] for msg in diagnostic_messages)
        has_error_messages = any(msg['error'] for msg in diagnostic_messages)
        has_ai_diagnostic = any("AI CALL DIAGNOSTIC" in msg['message'] for msg in diagnostic_messages)
        
        self.assertTrue(has_attempt_messages, "Should have attempt progress messages")
        self.assertTrue(has_error_messages, "Should have error messages")
        self.assertTrue(has_ai_diagnostic, "Should have AI call diagnostic messages")
        
        print("\n" + "="*80)
        print("DIAGNOSTIC OUTPUT TEST")
        print("="*80)
        print(f"Total diagnostic messages: {len(diagnostic_messages)}")
        print(f"Has attempt messages: {'✓' if has_attempt_messages else '✗'}")
        print(f"Has error messages: {'✓' if has_error_messages else '✗'}")
        print(f"Has AI diagnostics: {'✓' if has_ai_diagnostic else '✗'}")

def run_comprehensive_context_test():
    """Run all context preservation tests and provide a comprehensive report"""
    
    print("="*100)
    print("COMPREHENSIVE CONTEXT PRESERVATION TEST")
    print("Testing whether full contexts are preserved during improvement iterations")
    print("="*100)
    
    # Create test suite
    suite = unittest.TestSuite()
    suite.addTest(TestContextPreservation('test_context_preservation_in_script_creation'))
    suite.addTest(TestContextPreservation('test_error_history_accumulation_format'))
    suite.addTest(TestContextPreservation('test_original_script_preservation_on_failure'))
    suite.addTest(TestContextPreservation('test_code_context_evolution'))
    suite.addTest(TestContextPreservation('test_diagnostic_output_preservation'))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    
    # Summary report
    print("\n" + "="*100)
    print("FINAL SUMMARY")
    print("="*100)
    
    if result.wasSuccessful():
        print("🎉 ALL TESTS PASSED!")
        print("\nCONTEXT PRESERVATION VERIFICATION:")
        print("✅ Original script content is preserved through all iterations")
        print("✅ Error history is properly accumulated and formatted")
        print("✅ Full context (original + errors) is sent to AI for each attempt")
        print("✅ Multiple iteration cycles preserve all information")
        print("✅ Diagnostic information is properly captured")
        print("✅ Code context evolves appropriately between attempts")
        
        print("\nCONCLUSION:")
        print("The DeveloperAgent properly preserves full contexts during improvement")
        print("iterations. When a script fails, both the original script content and")
        print("error information are included in subsequent AI calls for correction.")
        
    else:
        print("❌ SOME TESTS FAILED!")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(f"Details: {traceback}")
    
    print("="*100)
    
    return result.wasSuccessful()

# For Slicer Python Console execution
def test_context_preservation():
    """Main function to run the context preservation test in Slicer"""
    try:
        return run_comprehensive_context_test()
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False

# Quick test function for interactive use
def quick_test():
    """Run a quick version of the context preservation test"""
    print("="*60)
    print("QUICK CONTEXT PRESERVATION TEST")
    print("="*60)
    
    test_instance = TestContextPreservation()
    test_instance.setUp()
    
    try:
        print("Testing context preservation in script creation...")
        test_instance.test_context_preservation_in_script_creation()
        print("✅ Context preservation test PASSED")
        
        print("\nTesting error history accumulation...")
        test_instance.test_error_history_accumulation_format()
        print("✅ Error history test PASSED")
        
        print("\n🎉 QUICK TEST COMPLETED SUCCESSFULLY!")
        print("Full contexts ARE preserved during improvement iterations.")
        return True
        
    except Exception as e:
        print(f"❌ Quick test failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False
    finally:
        test_instance.tearDown()

# Auto-run when executed
if __name__ == "__main__":
    success = run_comprehensive_context_test()
    sys.exit(0 if success else 1)
else:
    # When imported/executed in Slicer, show usage instructions
    print("Context Preservation Test loaded successfully!")
    print("Usage:")
    print("  test_context_preservation()  # Run full test suite")
    print("  quick_test()                 # Run quick test")
"""
Self-Validation Script for SMS Appointment Booking Agent
Runs automated tests to validate the implementation
"""

import sys
import os
import traceback
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_phone_validation():
    """Test phone number validation functionality"""
    print("🧪 Testing Phone Validation...")
    
    try:
        from nodes.phone_validator import validate_phone_number
        
        # Test valid US number
        result = validate_phone_number({
            'From': '+12345678901',
            'Body': 'Test message'
        })
        
        assert result['isValid'] is True, f"Expected valid phone, got: {result}"
        assert result['phoneNumber'] == '+12345678901', f"Expected formatted number, got: {result['phoneNumber']}"
        assert result['sessionId'] is not None, "Session ID should be generated"
        
        print("  ✅ Valid US phone number test passed")
        
        # Test invalid number
        result = validate_phone_number({
            'From': 'invalid-number',
            'Body': 'Test message'
        })
        
        assert result['isValid'] is False, f"Expected invalid phone, got: {result}"
        assert 'error' in result, "Error message should be present"
        
        print("  ✅ Invalid phone number test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Phone validation test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_groq_processor_structure():
    """Test Groq processor structure and methods"""
    print("🧪 Testing Groq Processor Structure...")
    
    try:
        from nodes.groq_processor import ConversationProcessor, process_user_message
        
        # Test processor initialization (without API call)
        processor = ConversationProcessor()
        assert hasattr(processor, 'get_system_prompt'), "get_system_prompt method should exist"
        assert hasattr(processor, 'validate_extracted_datetime'), "validate_extracted_datetime method should exist"
        
        print("  ✅ ConversationProcessor structure test passed")
        
        # Test datetime validation
        validation_result = processor.validate_extracted_datetime("2025-01-25 14:00")
        assert 'valid' in validation_result, "Validation result should contain 'valid' key"
        
        print("  ✅ Datetime validation structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Groq processor test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_error_handler_structure():
    """Test error handler structure"""
    print("🧪 Testing Error Handler Structure...")
    
    try:
        from nodes.error_handler import ErrorHandler, send_error_whatsapp
        
        # Test handler initialization
        handler = ErrorHandler()
        assert hasattr(handler, 'get_error_message'), "get_error_message method should exist"
        
        # Test error message generation
        message = handler.get_error_message('phone_validation')
        assert isinstance(message, str), "Error message should be string"
        assert len(message) > 0, "Error message should not be empty"
        assert 'phone number' in message.lower(), "Phone validation error should mention phone number"
        
        print("  ✅ Error handler structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error handler test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_fallback_handler_structure():
    """Test fallback handler structure"""
    print("🧪 Testing Fallback Handler Structure...")
    
    try:
        from nodes.fallback_handler import FallbackHandler, send_fallback_response
        
        # Test handler initialization
        handler = FallbackHandler()
        assert hasattr(handler, 'get_fallback_responses'), "get_fallback_responses method should exist"
        assert hasattr(handler, 'detect_intent_from_failed_message'), "detect_intent_from_failed_message method should exist"
        
        # Test intent detection
        intent = handler.detect_intent_from_failed_message("cancel my appointment")
        assert intent == 'cancellation', f"Expected 'cancellation' intent, got: {intent}"
        
        intent = handler.detect_intent_from_failed_message("I want to book tomorrow at 2pm")
        assert intent == 'date_time_unclear', f"Expected 'date_time_unclear' intent, got: {intent}"
        
        print("  ✅ Fallback handler structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Fallback handler test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_logger_structure():
    """Test logger structure"""
    print("🧪 Testing Logger Structure...")
    
    try:
        from nodes.logger import SMSAgentLogger, log_sms_failure
        
        # Test logger initialization
        logger = SMSAgentLogger()
        assert hasattr(logger, 'log_conversation_event'), "log_conversation_event method should exist"
        assert hasattr(logger, 'log_api_call'), "log_api_call method should exist"
        
        # Test conversation event logging
        result = logger.log_conversation_event(
            event_type="test_event",
            session_id="test-session",
            phone_number="+12345678901",
            data={"test": "data"}
        )
        
        assert result['logged'] is True, "Event should be logged successfully"
        assert result['sessionId'] == "test-session", "Session ID should match"
        
        print("  ✅ Logger structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Logger test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_langsmith_monitor_structure():
    """Test LangSmith monitor structure"""
    print("🧪 Testing LangSmith Monitor Structure...")
    
    try:
        from tracing.langsmith_monitor import LangSmithMonitor
        
        # Note: This will fail without actual API keys, but we can test structure
        print("  ⚠️  LangSmith monitor requires API keys - testing structure only")
        
        # Test that the class exists and has required methods
        assert hasattr(LangSmithMonitor, 'create_session_trace'), "create_session_trace method should exist"
        assert hasattr(LangSmithMonitor, 'trace_node_execution'), "trace_node_execution method should exist"
        assert hasattr(LangSmithMonitor, 'finalize_session_trace'), "finalize_session_trace method should exist"
        
        print("  ✅ LangSmith monitor structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ LangSmith monitor test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_main_app_structure():
    """Test main application structure"""
    print("🧪 Testing Main Application Structure...")
    
    try:
        from main import app, orchestrator, ConversationOrchestrator
        
        # Test FastAPI app
        assert app is not None, "FastAPI app should be initialized"
        
        # Test orchestrator
        assert isinstance(orchestrator, ConversationOrchestrator), "Orchestrator should be ConversationOrchestrator instance"
        assert hasattr(orchestrator, 'process_sms'), "process_sms method should exist"
        assert hasattr(orchestrator, '_get_or_create_session'), "_get_or_create_session method should exist"
        
        print("  ✅ Main application structure test passed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Main application test failed: {str(e)}")
        print(f"     Traceback: {traceback.format_exc()}")
        return False

def test_project_structure():
    """Test overall project structure"""
    print("🧪 Testing Project Structure...")
    
    required_files = [
        'graph.yaml',
        'main.py',
        'requirements.txt',
        'README.md',
        '.env.template',
        'nodes/phone_validator.py',
        'nodes/twilio_sender.py',
        'nodes/groq_processor.py',
        'nodes/calendly_checker.py',
        'nodes/calendly_creator.py',
        'nodes/error_handler.py',
        'nodes/fallback_handler.py',
        'nodes/logger.py',
        'tracing/langsmith_monitor.py',
        'tests/test_sms_agent.py',
        'tests/test_integration.py',
        'tests/conversation_simulation.py'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"  ❌ Missing files: {missing_files}")
        return False
    
    print("  ✅ All required files are present")
    return True

def run_self_validation():
    """Run all self-validation tests"""
    print("🚀 SMS Appointment Booking Agent - Self Validation")
    print("=" * 55)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    tests = [
        ("Project Structure", test_project_structure),
        ("Phone Validation", test_phone_validation),
        ("Groq Processor", test_groq_processor_structure),
        ("Error Handler", test_error_handler_structure),
        ("Fallback Handler", test_fallback_handler_structure),
        ("Logger", test_logger_structure),
        ("LangSmith Monitor", test_langsmith_monitor_structure),
        ("Main Application", test_main_app_structure)
    ]
    
    passed_tests = 0
    failed_tests = 0
    
    for test_name, test_function in tests:
        try:
            if test_function():
                passed_tests += 1
            else:
                failed_tests += 1
        except Exception as e:
            print(f"❌ {test_name} test crashed: {str(e)}")
            failed_tests += 1
        print()
    
    print("=" * 55)
    print("📊 VALIDATION SUMMARY")
    print("=" * 55)
    print(f"✅ Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"📈 Success Rate: {(passed_tests / (passed_tests + failed_tests)) * 100:.1f}%")
    
    if failed_tests == 0:
        print("\n🎉 ALL TESTS PASSED! The SMS agent is ready for deployment.")
        print("\n📋 Next Steps:")
        print("1. Configure your .env file with actual API keys")
        print("2. Test with real Twilio/Groq/Calendly credentials")
        print("3. Run conversation simulation: python tests/conversation_simulation.py")
        print("4. Deploy to your preferred platform")
        print("5. Configure Twilio webhook URL")
    else:
        print(f"\n⚠️  {failed_tests} tests failed. Please review the errors above.")
        print("\n🔧 Troubleshooting:")
        print("1. Ensure all dependencies are installed: pip install -r requirements.txt")
        print("2. Check Python version is 3.9+")
        print("3. Verify all files are present and properly formatted")
    
    print("\n" + "=" * 55)
    
    return failed_tests == 0

if __name__ == "__main__":
    success = run_self_validation()
    exit(0 if success else 1)

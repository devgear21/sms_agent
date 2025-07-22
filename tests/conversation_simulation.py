"""
End-to-End Conversation Simulation
Simulates complete SMS conversations to validate the entire workflow
"""

import asyncio
import json
import time
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any
from dataclasses import dataclass
import structlog

# Test imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import orchestrator, TwilioWebhook
from tracing.langsmith_monitor import langsmith_monitor

# Configure structured logging
logger = structlog.get_logger()

@dataclass
class ConversationStep:
    """Represents a step in a conversation simulation"""
    user_message: str
    expected_outcome: str  # "processing", "needs_more_info", "booked", "error", "fallback"
    description: str

@dataclass
class ConversationScenario:
    """Represents a complete conversation scenario"""
    name: str
    description: str
    phone_number: str
    steps: List[ConversationStep]
    expected_final_outcome: str

class ConversationSimulator:
    """Simulates SMS conversations to test the complete workflow"""
    
    def __init__(self):
        self.results = []
        self.logger = logger
    
    async def run_scenario(self, scenario: ConversationScenario) -> Dict[str, Any]:
        """
        Run a complete conversation scenario
        
        Args:
            scenario: The conversation scenario to simulate
        
        Returns:
            Dict with simulation results
        """
        
        self.logger.info(f"Starting conversation scenario: {scenario.name}",
                        phone_number=scenario.phone_number,
                        steps_count=len(scenario.steps))
        
        scenario_start_time = time.time()
        session_id = None
        step_results = []
        
        try:
            for i, step in enumerate(scenario.steps):
                self.logger.info(f"Executing step {i+1}/{len(scenario.steps)}: {step.description}",
                               user_message=step.user_message)
                
                # Create webhook data for this step
                webhook_data = TwilioWebhook(
                    MessageSid=f'SIM_{scenario.name}_{i+1}_{int(time.time())}',
                    AccountSid='AC_SIMULATION',
                    From=scenario.phone_number,
                    To='+19876543210',
                    Body=step.user_message
                )
                
                # Process the message
                step_start_time = time.time()
                result = await orchestrator.process_sms(webhook_data)
                step_duration = (time.time() - step_start_time) * 1000
                
                # Extract session ID from first step
                if session_id is None:
                    session_id = result.get('session_id', f'sim_{scenario.name}')
                
                # Record step result
                step_result = {
                    'step_number': i + 1,
                    'description': step.description,
                    'user_message': step.user_message,
                    'expected_outcome': step.expected_outcome,
                    'actual_outcome': result.get('status', 'unknown'),
                    'duration_ms': step_duration,
                    'success': result.get('status') == step.expected_outcome,
                    'result_data': result
                }
                step_results.append(step_result)
                
                self.logger.info(f"Step {i+1} completed",
                               expected=step.expected_outcome,
                               actual=result.get('status'),
                               success=step_result['success'],
                               duration_ms=step_duration)
                
                # Add delay between messages to simulate realistic conversation timing
                await asyncio.sleep(random.uniform(1, 3))
            
            # Calculate overall results
            scenario_duration = (time.time() - scenario_start_time) * 1000
            successful_steps = sum(1 for step in step_results if step['success'])
            scenario_success = successful_steps == len(scenario.steps)
            
            final_outcome = step_results[-1]['actual_outcome'] if step_results else 'no_steps'
            final_success = final_outcome == scenario.expected_final_outcome
            
            scenario_result = {
                'scenario_name': scenario.name,
                'description': scenario.description,
                'phone_number': scenario.phone_number,
                'session_id': session_id,
                'total_duration_ms': scenario_duration,
                'total_steps': len(scenario.steps),
                'successful_steps': successful_steps,
                'scenario_success': scenario_success,
                'expected_final_outcome': scenario.expected_final_outcome,
                'actual_final_outcome': final_outcome,
                'final_success': final_success,
                'overall_success': scenario_success and final_success,
                'step_results': step_results,
                'timestamp': datetime.now().isoformat()
            }
            
            self.results.append(scenario_result)
            
            self.logger.info(f"Scenario completed: {scenario.name}",
                           overall_success=scenario_result['overall_success'],
                           successful_steps=f"{successful_steps}/{len(scenario.steps)}",
                           total_duration_ms=scenario_duration)
            
            return scenario_result
        
        except Exception as e:
            error_result = {
                'scenario_name': scenario.name,
                'description': scenario.description,
                'phone_number': scenario.phone_number,
                'session_id': session_id,
                'error': str(e),
                'overall_success': False,
                'step_results': step_results,
                'timestamp': datetime.now().isoformat()
            }
            
            self.results.append(error_result)
            
            self.logger.error(f"Scenario failed: {scenario.name}",
                            error=str(e))
            
            return error_result
    
    async def run_all_scenarios(self, scenarios: List[ConversationScenario]) -> Dict[str, Any]:
        """
        Run all conversation scenarios
        
        Args:
            scenarios: List of scenarios to run
        
        Returns:
            Dict with overall simulation results
        """
        
        self.logger.info("Starting conversation simulation suite",
                        total_scenarios=len(scenarios))
        
        suite_start_time = time.time()
        
        # Run all scenarios
        for scenario in scenarios:
            await self.run_scenario(scenario)
            # Delay between scenarios
            await asyncio.sleep(2)
        
        suite_duration = (time.time() - suite_start_time) * 1000
        
        # Calculate overall statistics
        successful_scenarios = sum(1 for result in self.results if result.get('overall_success', False))
        total_steps = sum(result.get('total_steps', 0) for result in self.results)
        successful_steps = sum(result.get('successful_steps', 0) for result in self.results)
        
        suite_results = {
            'total_scenarios': len(scenarios),
            'successful_scenarios': successful_scenarios,
            'scenario_success_rate': successful_scenarios / len(scenarios) if scenarios else 0,
            'total_steps': total_steps,
            'successful_steps': successful_steps,
            'step_success_rate': successful_steps / total_steps if total_steps else 0,
            'total_duration_ms': suite_duration,
            'average_scenario_duration_ms': suite_duration / len(scenarios) if scenarios else 0,
            'scenario_results': self.results,
            'timestamp': datetime.now().isoformat()
        }
        
        self.logger.info("Simulation suite completed",
                        successful_scenarios=f"{successful_scenarios}/{len(scenarios)}",
                        scenario_success_rate=f"{suite_results['scenario_success_rate']:.2%}",
                        step_success_rate=f"{suite_results['step_success_rate']:.2%}",
                        total_duration_ms=suite_duration)
        
        return suite_results
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a human-readable report of simulation results"""
        
        report = f"""
SMS Appointment Booking Agent - Conversation Simulation Report
============================================================

Generated: {results['timestamp']}

OVERALL RESULTS:
- Total Scenarios: {results['total_scenarios']}
- Successful Scenarios: {results['successful_scenarios']}
- Scenario Success Rate: {results['scenario_success_rate']:.2%}
- Total Steps: {results['total_steps']}
- Successful Steps: {results['successful_steps']}
- Step Success Rate: {results['step_success_rate']:.2%}
- Total Duration: {results['total_duration_ms']:.0f}ms
- Average Scenario Duration: {results['average_scenario_duration_ms']:.0f}ms

SCENARIO DETAILS:
"""
        
        for scenario_result in results['scenario_results']:
            success_icon = "✅" if scenario_result.get('overall_success') else "❌"
            
            report += f"""
{success_icon} {scenario_result['scenario_name']}
   Description: {scenario_result['description']}
   Phone: {scenario_result['phone_number']}
   Session: {scenario_result.get('session_id', 'N/A')}
   Duration: {scenario_result.get('total_duration_ms', 0):.0f}ms
   Steps: {scenario_result.get('successful_steps', 0)}/{scenario_result.get('total_steps', 0)}
   Expected Outcome: {scenario_result.get('expected_final_outcome', 'N/A')}
   Actual Outcome: {scenario_result.get('actual_final_outcome', 'N/A')}
"""
            
            if scenario_result.get('error'):
                report += f"   Error: {scenario_result['error']}\n"
            
            # Add step details for failed scenarios
            if not scenario_result.get('overall_success'):
                step_results = scenario_result.get('step_results', [])
                for step in step_results:
                    step_icon = "✅" if step.get('success') else "❌"
                    report += f"      {step_icon} Step {step['step_number']}: {step['description']}\n"
                    if not step.get('success'):
                        report += f"         Expected: {step['expected_outcome']}, Got: {step['actual_outcome']}\n"
        
        return report

def create_test_scenarios() -> List[ConversationScenario]:
    """Create test scenarios for conversation simulation"""
    
    # Calculate tomorrow for date references
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    scenarios = [
        ConversationScenario(
            name="successful_booking_clear_request",
            description="User provides clear date/time and successfully books appointment",
            phone_number="+15551234567",
            steps=[
                ConversationStep(
                    user_message="I want to book an appointment tomorrow at 2pm",
                    expected_outcome="booked",
                    description="Clear appointment request with specific date and time"
                )
            ],
            expected_final_outcome="booked"
        ),
        
        ConversationScenario(
            name="successful_booking_multi_step",
            description="User books appointment through multiple clarifying messages",
            phone_number="+15559876543",
            steps=[
                ConversationStep(
                    user_message="I need to schedule a meeting",
                    expected_outcome="processing",
                    description="Initial vague request"
                ),
                ConversationStep(
                    user_message="Tomorrow at 3pm",
                    expected_outcome="booked",
                    description="Clarified with specific time"
                )
            ],
            expected_final_outcome="booked"
        ),
        
        ConversationScenario(
            name="no_availability_alternatives",
            description="Requested time not available, system offers alternatives",
            phone_number="+15555555555",
            steps=[
                ConversationStep(
                    user_message="Can I meet at 11pm tonight?",
                    expected_outcome="processing",
                    description="Request outside business hours"
                )
            ],
            expected_final_outcome="processing"
        ),
        
        ConversationScenario(
            name="invalid_phone_number",
            description="Invalid phone number triggers error flow",
            phone_number="invalid-phone",
            steps=[
                ConversationStep(
                    user_message="Book appointment tomorrow",
                    expected_outcome="error",
                    description="Message from invalid phone number"
                )
            ],
            expected_final_outcome="error"
        ),
        
        ConversationScenario(
            name="unclear_messages_fallback",
            description="Unclear messages trigger fallback responses",
            phone_number="+15551111111",
            steps=[
                ConversationStep(
                    user_message="asdfgh jklqwerty",
                    expected_outcome="fallback",
                    description="Gibberish message triggers fallback"
                ),
                ConversationStep(
                    user_message="Friday at 10am",
                    expected_outcome="booked",
                    description="Clear follow-up after fallback"
                )
            ],
            expected_final_outcome="booked"
        ),
        
        ConversationScenario(
            name="weekend_booking_attempt",
            description="User tries to book on weekend, gets business hours error",
            phone_number="+15552222222",
            steps=[
                ConversationStep(
                    user_message="This Saturday at 2pm",
                    expected_outcome="processing",
                    description="Weekend booking attempt"
                )
            ],
            expected_final_outcome="processing"
        ),
        
        ConversationScenario(
            name="reschedule_request",
            description="User requests to reschedule existing appointment",
            phone_number="+15553333333",
            steps=[
                ConversationStep(
                    user_message="I need to reschedule my appointment",
                    expected_outcome="processing",
                    description="Reschedule request"
                ),
                ConversationStep(
                    user_message="Next Tuesday at 1pm instead",
                    expected_outcome="booked",
                    description="New time specification"
                )
            ],
            expected_final_outcome="booked"
        ),
        
        ConversationScenario(
            name="help_request",
            description="User asks for help using the system",
            phone_number="+15554444444",
            steps=[
                ConversationStep(
                    user_message="How does this work?",
                    expected_outcome="processing",
                    description="Help request"
                ),
                ConversationStep(
                    user_message="Monday at 9am",
                    expected_outcome="booked",
                    description="Booking after help"
                )
            ],
            expected_final_outcome="booked"
        )
    ]
    
    return scenarios

async def main():
    """Main function to run conversation simulations"""
    
    print("SMS Appointment Booking Agent - Conversation Simulation")
    print("======================================================")
    print()
    
    # Create simulator
    simulator = ConversationSimulator()
    
    # Create test scenarios
    scenarios = create_test_scenarios()
    
    print(f"Created {len(scenarios)} test scenarios:")
    for i, scenario in enumerate(scenarios, 1):
        print(f"  {i}. {scenario.name}: {scenario.description}")
    
    print("\nStarting simulation...")
    print()
    
    # Run all scenarios
    results = await simulator.run_all_scenarios(scenarios)
    
    # Generate and display report
    report = simulator.generate_report(results)
    print(report)
    
    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"conversation_simulation_results_{timestamp}.json"
    report_file = f"conversation_simulation_report_{timestamp}.txt"
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nResults saved to:")
    print(f"  - {results_file}")
    print(f"  - {report_file}")
    
    # Summary
    success_rate = results['scenario_success_rate']
    if success_rate >= 0.9:
        print(f"\n🎉 Excellent! {success_rate:.1%} success rate")
    elif success_rate >= 0.7:
        print(f"\n👍 Good! {success_rate:.1%} success rate")
    else:
        print(f"\n⚠️  Needs improvement: {success_rate:.1%} success rate")
    
    return results

if __name__ == "__main__":
    # Run the simulation
    asyncio.run(main())

"""
Calendly Availability Checker Node
Queries Calendly API to check appointment availability
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from langsmith import traceable
import structlog

# Configure structured logging
logger = structlog.get_logger()

class CalendlyAvailabilityChecker:
    def __init__(self):
        """Initialize Calendly API client"""
        self.api_token = os.getenv('CALENDLY_API_TOKEN')
        self.user_uri = os.getenv('CALENDLY_USER_URI')
        
        if not self.api_token or not self.user_uri:
            raise ValueError("CALENDLY_API_TOKEN and CALENDLY_USER_URI environment variables are required")
        
        self.base_url = "https://api.calendly.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        logger.info("Calendly availability checker initialized", user_uri=self.user_uri)

    @traceable(
        name="check_calendly_availability",
        tags=["calendly", "availability", "api"],
        metadata={"component": "calendly_checker"}
    )
    def check_availability(self, requested_datetime: str, session_id: str, 
                          duration_minutes: int = 30) -> Dict[str, Any]:
        """
        Check availability for a specific datetime on Calendly
        
        Args:
            requested_datetime: ISO format datetime string
            session_id: Session identifier
            duration_minutes: Appointment duration in minutes
        
        Returns:
            Dict with availability information
        """
        
        logger.info("Checking Calendly availability", 
                    requested_datetime=requested_datetime,
                    session_id=session_id,
                    duration=duration_minutes)
        
        try:
            # Parse requested datetime
            requested_dt = datetime.fromisoformat(requested_datetime.replace('Z', '+00:00'))
            
            # Get event types first
            event_types = self._get_event_types()
            if not event_types:
                return {
                    "isAvailable": False,
                    "error": "No event types found",
                    "availableSlots": [],
                    "suggestedAlternatives": []
                }
            
            # Use the first event type (could be made configurable)
            event_type_uri = event_types[0]['uri']
            
            # Check availability for the specific time
            start_time = requested_dt.replace(second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # Get available times around the requested time
            available_times = self._get_available_times(
                event_type_uri=event_type_uri,
                start_time=start_time - timedelta(hours=2),  # 2 hours before
                end_time=start_time + timedelta(hours=4)     # 4 hours after
            )
            
            # Check if exact time is available
            exact_match = any(
                abs((datetime.fromisoformat(slot['start_time'].replace('Z', '+00:00')) - start_time).total_seconds()) < 60
                for slot in available_times
            )
            
            if exact_match:
                logger.info("Exact time slot available", 
                           requested_datetime=requested_datetime,
                           session_id=session_id)
                
                return {
                    "isAvailable": True,
                    "exactMatch": True,
                    "confirmedSlot": {
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "event_type_uri": event_type_uri
                    },
                    "availableSlots": self._format_available_slots(available_times[:5]),
                    "sessionId": session_id
                }
            
            else:
                # Suggest alternative times
                alternatives = self._find_alternative_slots(available_times, start_time)
                
                logger.info("Exact time not available, suggesting alternatives", 
                           alternatives_count=len(alternatives),
                           session_id=session_id)
                
                return {
                    "isAvailable": False,
                    "exactMatch": False,
                    "availableSlots": self._format_available_slots(available_times[:5]),
                    "suggestedAlternatives": alternatives[:3],  # Top 3 alternatives
                    "eventTypeUri": event_type_uri,
                    "sessionId": session_id
                }
        
        except Exception as e:
            logger.error("Calendly availability check failed", 
                        error=str(e),
                        requested_datetime=requested_datetime,
                        session_id=session_id)
            
            return {
                "isAvailable": False,
                "error": f"Availability check failed: {str(e)}",
                "availableSlots": [],
                "suggestedAlternatives": [],
                "sessionId": session_id
            }

    def _get_event_types(self) -> List[Dict[str, Any]]:
        """Get available event types for the user"""
        try:
            url = f"{self.base_url}/event_types"
            params = {"user": self.user_uri}
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get('collection', [])
            
        except Exception as e:
            logger.error("Failed to get event types", error=str(e))
            return []

    def _get_available_times(self, event_type_uri: str, start_time: datetime, 
                            end_time: datetime) -> List[Dict[str, Any]]:
        """Get available time slots from Calendly"""
        try:
            url = f"{self.base_url}/event_type_available_times"
            params = {
                "event_type": event_type_uri,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get('collection', [])
            
        except Exception as e:
            logger.error("Failed to get available times", error=str(e))
            return []

    def _format_available_slots(self, slots: List[Dict[str, Any]]) -> List[str]:
        """Format available slots for user display"""
        formatted_slots = []
        
        for slot in slots:
            try:
                start_time = datetime.fromisoformat(slot['start_time'].replace('Z', '+00:00'))
                formatted_time = start_time.strftime("%A, %B %d at %I:%M %p")
                formatted_slots.append(formatted_time)
            except Exception as e:
                logger.warning("Failed to format slot", slot=slot, error=str(e))
                continue
        
        return formatted_slots

    def _find_alternative_slots(self, available_times: List[Dict[str, Any]], 
                               requested_time: datetime) -> List[str]:
        """Find alternative time slots close to the requested time"""
        alternatives = []
        
        # Sort by proximity to requested time
        def time_distance(slot):
            try:
                slot_time = datetime.fromisoformat(slot['start_time'].replace('Z', '+00:00'))
                return abs((slot_time - requested_time).total_seconds())
            except:
                return float('inf')
        
        sorted_slots = sorted(available_times, key=time_distance)
        
        # Get closest alternatives
        for slot in sorted_slots[:5]:
            try:
                start_time = datetime.fromisoformat(slot['start_time'].replace('Z', '+00:00'))
                
                # Skip if too far from requested time (more than 2 days)
                if abs((start_time - requested_time).total_seconds()) > 172800:  # 2 days
                    continue
                
                formatted_time = start_time.strftime("%A, %B %d at %I:%M %p")
                alternatives.append(formatted_time)
                
            except Exception as e:
                logger.warning("Failed to process alternative slot", slot=slot, error=str(e))
                continue
        
        return alternatives

# Global checker instance
availability_checker = CalendlyAvailabilityChecker()

@traceable(
    name="check_calendly_availability",
    tags=["calendly", "availability", "scheduling"],
    metadata={"component": "availability_check"}
)
def check_calendly_availability(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for checking Calendly availability
    
    Args:
        inputs: Dict containing requestedDateTime, sessionId
    
    Returns:
        Dict with availability results
    """
    
    requested_datetime = inputs.get('requestedDateTime')
    session_id = inputs.get('sessionId', '')
    duration = inputs.get('duration', 30)  # Default 30 minutes
    
    if not requested_datetime:
        return {
            "isAvailable": False,
            "error": "No datetime specified",
            "availableSlots": [],
            "suggestedAlternatives": [],
            "sessionId": session_id
        }
    
    return availability_checker.check_availability(
        requested_datetime=requested_datetime,
        session_id=session_id,
        duration_minutes=duration
    )

# Test function
if __name__ == "__main__":
    # Test availability checking
    test_datetime = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    
    print("Testing Calendly availability check...")
    print(f"Checking availability for: {test_datetime.isoformat()}")
    
    result = check_calendly_availability({
        "requestedDateTime": test_datetime.isoformat(),
        "sessionId": "test-session-availability"
    })
    
    print(f"Result: {result}")
    print(f"Available: {result.get('isAvailable')}")
    print(f"Alternatives: {result.get('suggestedAlternatives', [])}")

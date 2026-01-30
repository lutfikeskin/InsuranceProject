import sys
import os
import logging
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from modules.extraction.pipeline import GeminiExtractionPipeline, ExtractionContext
from modules.extraction.pdf_ops import PdfProcessor

# Configure logging to see our proof
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modules.extraction.pipeline")
logger.setLevel(logging.INFO)

class MockResponse:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = MagicMock()
        self.usage_metadata.prompt_token_count = 0
        self.usage_metadata.candidates_token_count = 0

class DryRunPipeline(GeminiExtractionPipeline):
    """Subclass that completely mocks out the network layer cost-free."""
    
    def __init__(self):
        # Bypass init_db and usage service for this test
        self.client = MagicMock()
        self.usage_service = MagicMock()
        self.usage_service.is_over_budget.return_value = False
        self.engine = MagicMock()
        self.session = MagicMock()

    def _upload_to_gemini(self, file_bytes):
        print("MOCK: Uploaded file (No Cost)")
        return MagicMock(name="mock_file")

    def _call_gemini(self, model, contents, config, request_type="extraction"):
        print(f"MOCK: Calling Gemini [{request_type}] - (No Cost)")
        # Return minimal valid JSON for each step to keep pipeline moving
        if request_type == "classification":
            return MockResponse('{"policy_type": "commercial_auto", "confidence": "high"}')
        elif request_type == "locator":
            # Return signals at specific pages to test slicing
            return MockResponse('{"declarations": [1], "vehicles": [50], "drivers": [50], "coverages": [10]}')
        elif request_type == "scout":
            return MockResponse('{"premium_signals": [], "vehicle_schedule_signals": [], "driver_schedule_signals": [], "coverage_schedule_signals": []}')
        
        # Extraction responses
        return MockResponse('{}')

def test_large_doc_behavior():
    print("="*60)
    print("TEST: Verifying Large Document Strategy (100 Pages)")
    print("GOAL: Confirm 'Short Doc Strategy' is DISABLED and Slicing is USED.")
    print("="*60)

    pipeline = DryRunPipeline()
    
    # Mock Processor to report 100 pages
    mock_processor = MagicMock(spec=PdfProcessor)
    mock_processor.get_page_count.return_value = 100 # <--- THE KEY TEST DATA
    mock_processor.get_hash.return_value = "dummy_hash"
    mock_processor.get_dimensions.return_value = []
    
    # Mock creating slices (don't actually manipulate bytes)
    mock_processor.create_slice.return_value = b"mock_slice_bytes"

    # Patch PdfProcessor in the module to return our mock
    with patch('modules.extraction.pipeline.PdfProcessor', return_value=mock_processor):
        # Run with dummy bytes
        pipeline.run(b"dummy_bytes", force_refresh=True)

if __name__ == "__main__":
    test_large_doc_behavior()

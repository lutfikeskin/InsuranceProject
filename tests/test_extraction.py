import pytest
from modules.extraction.pipeline import GeminiExtractionPipeline
from modules.extraction.schemas import UNIVERSAL_SCOUT_SCHEMA

class TestExtractionLogic:
    
    def test_get_pages_for_section_scout_logic(self):
        """Verify that 1-based Scout pages are correctly converted to 0-based slices."""
        pipeline = GeminiExtractionPipeline(api_key="dummy")
        
        # Scenario: Scout found Premium on Page 1 and 5
        # Logic adds +/- 1 page context
        # Page 1 -> 0, 1, 2 (but 0 min) -> 1, 2 (1-based) -> 0, 1 (0-based)
        # Page 5 -> 4, 5, 6 -> 3, 4, 5 (0-based)
        
        # Wait, the pipeline logic ALREADY receives the expanded list from map_scout_pages
        # Let's test _get_pages_for_section assuming the section map is already populated
        
        section_map = {
            "declarations": [1, 2, 5, 6] # 1-based input
        }
        
        # Act
        pages = pipeline._get_pages_for_section(section_map, "declarations", total_pages=10)
        
        # Assert (Expect 0-based)
        assert pages == [0, 1, 4, 5]

    def test_apply_auto_liability_csl_dominance(self):
        """Verify CSL Supremacy rule prunes split limits."""
        pipeline = GeminiExtractionPipeline(api_key="dummy")
        
        coverages = [
            {"family": "auto_liability", "limit_structure": "csl", "combined_single_limit": 1000000},
            {"family": "auto_liability", "limit_structure": "split", "per_person": 100000, "per_accident": 300000},
            {"family": "general_liability", "limit_structure": "per_occurrence", "per_occurrence": 1000000}
        ]
        
        pipeline._apply_auto_liability_rules(coverages, "commercial_auto")
        
        # Should keep CSL and GL, remove Split Auto
        assert len(coverages) == 2
        families = [c["family"] for c in coverages]
        structures = [c["limit_structure"] for c in coverages]
        
        assert "auto_liability" in families
        assert "general_liability" in families
        assert "split" not in structures
        assert "csl" in structures

    def test_apply_auto_liability_ignore_non_auto(self):
        """Verify logic doesn't touch GL policies."""
        pipeline = GeminiExtractionPipeline(api_key="dummy")
        
        coverages = [
            {"family": "auto_liability", "limit_structure": "split"}, # Should ideally not exist in GL but if it did...
            {"family": "general_liability", "limit_structure": "per_occurrence"}
        ]
        
        # Act with WRONG policy type
        pipeline._apply_auto_liability_rules(coverages, "general_liability")
        
        # Assert: No changes because policy_type is not auto
        assert len(coverages) == 2 

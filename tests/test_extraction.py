import pytest
from modules.extraction.pipeline import GeminiExtractionPipeline

class TestExtractionLogic:
    @pytest.mark.skip(reason="GeminiExtractionPipeline no longer exposes _get_pages_for_section (scout refactor).")
    def test_get_pages_for_section_scout_logic(self):
        """Verify that 1-based Scout pages are correctly converted to 0-based slices."""
        pipeline = GeminiExtractionPipeline(api_key="dummy")
        
        section_map = {
            "declarations": [1, 2, 5, 6]
        }
        
        pages = pipeline._get_pages_for_section(section_map, "declarations", total_pages=10)
        
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
            {"family": "auto_liability", "limit_structure": "split"},
            {"family": "general_liability", "limit_structure": "per_occurrence"}
        ]
        
        pipeline._apply_auto_liability_rules(coverages, "general_liability")
        
        assert len(coverages) == 2 

import hashlib
import io
import pypdf

class PdfProcessor:
    """
    Handles all PDF manipulation logic: hashing, dimension reading, and slicing.
    Isolates pypdf dependency from the main pipeline.
    """
    
    def __init__(self, file_bytes: bytes):
        self.file_bytes = file_bytes
        self._reader = None # Lazy load

    @property
    def reader(self):
        if self._reader is None:
            self._reader = pypdf.PdfReader(io.BytesIO(self.file_bytes))
        return self._reader

    def get_hash(self) -> str:
        """Returns SHA256 hash of the file bytes."""
        return hashlib.sha256(self.file_bytes).hexdigest()

    def get_dimensions(self) -> list[dict]:
        """Returns list of {width, height} for each page."""
        try:
            dims = []
            for page in self.reader.pages:
                dims.append({
                    "width": float(page.mediabox.width), 
                    "height": float(page.mediabox.height)
                })
            return dims
        except Exception as e:
            print(f"Error getting dimensions: {e}")
            return []

    def create_slice(self, page_indices: list[int]) -> bytes:
        """
        Creates a new PDF bytes object containing only the specified pages.
        Pages are 0-indexed.
        """
        try:
            writer = pypdf.PdfWriter()
            total_pages = len(self.reader.pages)
            
            valid_pages = [p for p in page_indices if 0 <= p < total_pages]
            
            if not valid_pages:
                # Fallback: if no valid pages, return the first page to avoid empty PDF error
                # or maybe just return self.file_bytes?
                # For safety in extraction, a single page is better than a full doc crash
                print(f"WARNING: PdfProcessor found no valid pages to slice for indices {page_indices}. Fallback to page 0.")
                valid_pages = [0]
            
            for p in valid_pages:
                writer.add_page(self.reader.pages[p])
            
            out_buffer = io.BytesIO()
            writer.write(out_buffer)
            return out_buffer.getvalue()
            
        except Exception as e:
            print(f"PdfProcessor Error: {e}")
            # Fallback to full document on critical slicing error
            return self.file_bytes

    def get_page_count(self) -> int:
        return len(self.reader.pages)

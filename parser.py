import logging
import re

logger = logging.getLogger(__name__)

class PlateParser:
    """
    Class for parsing license plate text according to the format rules
    """
    
    def __init__(self):
        """
        Initialize the plate parser with regex patterns
        """
        # Regex for complete license plate format
        # [localID][modelID][mainID]
        # localID: 2 digits
        # modelID: 1 or 2 alphanumeric characters
        # mainID: 4 or 5 digits
        self.plate_pattern = re.compile(r'^(\d{2})([A-Za-z0-9]{1,2})(\d{4,5})$')
        
        # Fallback patterns for partial matches
        self.localID_pattern = re.compile(r'^\d{2}')
        self.modelID_pattern = re.compile(r'[A-Za-z0-9]{1,2}')
        self.mainID_pattern = re.compile(r'\d{4,5}$')
    
    def clean_text(self, text):
        """
        Clean the OCR output for better parsing
        
        Args:
            text: Raw OCR output
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
            
        # Remove common OCR errors and normalize characters
        replacements = {
            'O': '0',  # Letter O to zero
            'I': '1',  # Letter I to one
            'Z': '2',  # Sometimes Z is mistaken for 2
            'S': '5',  # Sometimes S is mistaken for 5
            'B': '8',  # Sometimes B is mistaken for 8
            'G': '6',  # Sometimes G is mistaken for 6
            'D': '0',  # Sometimes D is mistaken for 0
            'Q': '0',  # Sometimes Q is mistaken for 0
            ' ': '',   # Remove spaces
            '-': '',   # Remove hyphens
            '.': '',   # Remove periods
            ',': '',   # Remove commas
        }
        
        # Apply replacements
        cleaned = text.upper()
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        
        # Remove non-alphanumeric characters
        cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
        
        return cleaned
    
    def parse(self, text):
        """
        Parse the license plate text according to the format rules
        
        Args:
            text: Raw OCR text from the license plate
            
        Returns:
            Dictionary with parsed plate components or None if parsing failed
        """
        if not text:
            logger.warning("Empty text input for parsing")
            return None
            
        # Clean the text
        cleaned_text = self.clean_text(text)
        logger.info(f"Cleaned text for parsing: {cleaned_text}")
        
        # Try exact pattern match first
        match = self.plate_pattern.match(cleaned_text)
        if match:
            localID, modelID, mainID = match.groups()
            logger.info(f"Exact match found: localID={localID}, modelID={modelID}, mainID={mainID}")
            return {
                "localID": localID,
                "modelID": modelID,
                "mainID": mainID,
                "full_plate": f"{localID}{modelID}{mainID}"
            }
        
        # If exact match fails, try best-effort parsing
        try:
            # Try to extract each part separately
            localID_match = self.localID_pattern.search(cleaned_text)
            localID = localID_match.group(0) if localID_match else ""
            
            # For modelID, find characters after the localID
            if localID and len(cleaned_text) > 2:
                rest = cleaned_text[2:]
                modelID_candidates = self.modelID_pattern.findall(rest)
                modelID = modelID_candidates[0] if modelID_candidates else ""
                
                # Try to find mainID after modelID
                if modelID and len(rest) > len(modelID):
                    mainID_match = self.mainID_pattern.search(rest[len(modelID):])
                    mainID = mainID_match.group(0) if mainID_match else ""
                else:
                    mainID = ""
            else:
                modelID = ""
                mainID = ""
            
            # Check if we have all parts
            if localID and modelID and mainID:
                logger.info(f"Partial match: localID={localID}, modelID={modelID}, mainID={mainID}")
                return {
                    "localID": localID,
                    "modelID": modelID,
                    "mainID": mainID,
                    "full_plate": f"{localID}{modelID}{mainID}"
                }
            else:
                logger.warning("Could not extract all license plate parts")
                return None
                
        except Exception as e:
            logger.error(f"Error parsing license plate text: {str(e)}")
            return None
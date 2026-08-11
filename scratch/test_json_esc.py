import re

broken = r"\esumeSubHeadingListStart \esumeItem \esumeProjectHeading"
fixed = re.sub(r"\\esume([A-Za-z])", r"\\resume\1", broken)
print("Broken:", broken)
print("Fixed:", fixed)

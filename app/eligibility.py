"""Conservative, evidence-carrying eligibility extraction; not visa advice."""
import re
from html import unescape
from html.parser import HTMLParser


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('p', 'li', 'br', 'div', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
        if tag in ('p', 'li', 'div'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(value):
    parser = _Text()
    parser.feed(unescape(value or ''))
    return '\n'.join(re.sub(r'\s+', ' ', s).strip() for s in ''.join(parser.parts).splitlines() if s.strip())


def extract_eligibility(value):
    text = plain_text(value)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n', text) if s.strip()]
    positive, negative, sponsorship_yes, sponsorship_no, work = [], [], [], [], []
    for sentence in sentences:
        s = sentence.lower().replace('’', "'")
        if s.endswith('?'):
            continue  # A question is not an eligibility assertion.
        # Citizenship restrictions must be explicit. Clearance/work rights alone
        # do not establish nationality, visa type, or sponsorship availability.
        if re.search(r'(?:must be|only|restricted to|limited to|require[sd]?)[^.!?]{0,65}(?:australian (?:citizen|permanent resident)|citizenship)', s) or re.search(r'(?:australian citizens?|citizens or permanent residents)[^.!?]{0,25}\bonly\b', s):
            negative.append(sentence)
        if re.search(r'international (?:students|graduates|applicants|candidates)[^.!?]{0,35}(?:not eligible|cannot apply|not accepted|not considered)', s) or re.search(r'(?:do not|cannot|unable to) (?:accept|consider)[^.!?]{0,35}international', s):
            negative.append(sentence)
        if (re.search(r'international (?:students|graduates|applicants|candidates)', s) or re.search(r'(?:student|graduate|485|500)[^.!?]{0,30}visa', s)) and re.search(r'\b(?:welcome|accept|eligible|encourage|may apply|can apply|open to)\b', s) and not re.search(r'\b(?:not|cannot|unable|ineligible)\b', s):
            positive.append(sentence)
        if re.search(r'(?:work(?:ing)? rights|work authori[sz]ation|security clearance)', s):
            work.append(sentence)
        if re.search(r'(?:sponsor|sponsorship)', s) and re.search(r'(?:visa|work|immigration|sponsorship)', s):
            if re.search(r'\b(?:no|not|cannot|unable|without|won\x27t|don\x27t|doesn\x27t|unavailable)\b', s):
                sponsorship_no.append(sentence)
            elif re.search(r'(?:will sponsor|we sponsor|sponsorship (?:is )?available|offer[^.!?]{0,20}sponsorship|happy to sponsor|can sponsor)', s):
                sponsorship_yes.append(sentence)
    # Conflicting evidence is presented for review, not resolved optimistically.
    accepted = None if positive and negative else False if negative else True if positive else None
    sponsored = None if sponsorship_yes and sponsorship_no else False if sponsorship_no else True if sponsorship_yes else None
    evidence = list(dict.fromkeys(positive + negative + sponsorship_yes + sponsorship_no + work))
    return {
        'accepts_international': accepted,
        'sponsorship_available': sponsored,
        'work_rights_note': '\n'.join(work)[:2000] or None,
        'eligibility_evidence': '\n'.join(evidence)[:4000] or None,
    }

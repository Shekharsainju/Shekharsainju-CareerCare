"""Live public employer feeds. Only complete snapshots close missing listings."""
import json
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import requests
from .eligibility import extract_eligibility, plain_text

HEADERS = {'User-Agent': 'InternInsiderAU/1.0 (public employer job discovery)'}
TIMEOUT = 20
_deadline = ContextVar('scrape_deadline', default=None)
COMPANY_BOARDS = [
    {'platform': 'smartrecruiters', 'token': 'KPMGAustralia1', 'display_name': 'KPMG Australia'},
    {'platform': 'smartrecruiters', 'token': 'AECOM2', 'display_name': 'AECOM'},
    {'platform': 'smartrecruiters', 'token': 'BoschGroup', 'display_name': 'Bosch Group'},
    {'platform': 'smartrecruiters', 'token': 'TurnerTownsend', 'display_name': 'Turner & Townsend'},
    {'platform': 'smartrecruiters', 'token': 'Canva', 'display_name': 'Canva'},
    {'platform': 'greenhouse', 'token': 'thetradedesk', 'display_name': 'The Trade Desk'},
    {'platform': 'lever', 'token': 'shopback-2', 'display_name': 'ShopBack'},
    {'platform': 'greenhouse', 'token': 'imc', 'display_name': 'IMC Trading'},
    {'platform': 'greenhouse', 'token': 'akunacapital', 'display_name': 'Akuna Capital'},
    {'platform': 'greenhouse', 'token': 'databricks', 'display_name': 'Databricks'},
    {'platform': 'greenhouse', 'token': 'cloudflare', 'display_name': 'Cloudflare'},
]


class SourceRows(list):
    def __init__(self, rows=(), status='ok', message=None):
        super().__init__(rows)
        self.status, self.message = status, message


class ScrapeBatch(list):
    def __init__(self):
        super().__init__()
        self.reports = {}


def _title_matches_intern_or_grad(title):
    if re.search(r'\b(senior|principal|director|recruitment|recruiter|phd|postdoctoral|scholarship|simulation)\b', title, re.I):
        return False
    return bool(re.search(r'\b(intern(ship)?|graduates?|undergraduate|vacationer|studentship|co-op|working student)\b', title, re.I))


def _location_is_australian(location, country=None):
    if country:
        return country.lower() in ('au', 'aus', 'australia')
    s = location.lower()
    if re.search(r'\baustralia\b|\bau\b', s):
        return True
    if re.search(r'\b(united states|usa|united kingdom|uk|canada|british columbia|new zealand|singapore|hong kong|india|germany|france|florida|california|scotland|england|fl|ca|ny|tx|bc|on)\b', s):
        return False
    # Ambiguous city/state names (Newcastle, Victoria, WA) need country evidence.
    return bool(re.search(r'\b(sydney|melbourne|brisbane|adelaide|canberra|hobart|darwin|wollongong|gold coast|nsw|qld)\b', s))


def _classify_field(title, department=''):
    s = f'{title} {department}'.lower()
    rules = [
        ('Data', r'data|analytics|machine learning|\bai\b'),
        ('Software', r'software|developer|backend|frontend|devops|\bsre\b|cyber|information technology'),
        ('Design', r'landscape|architectur|\bdesign'),
        ('Engineering', r'engineer|construction|civil|mechanical|electrical'),
        ('Consulting', r'consult|advisory|audit'),
        ('Finance', r'finance|financial|accounting|banking|analyst'),
        ('Marketing', r'marketing|growth|brand|social media|content'),
        ('Research', r'research|scientist|studentship'),
        ('Government', r'policy|government|public sector'),
        ('Operations', r'project manag|supply chain|logistics|business development|human resources'),
    ]
    return next((field for field, pattern in rules if re.search(pattern, s)), None)


def _infer_accepts_international(description_text):
    return extract_eligibility(description_text)['accepts_international']


def _safe_get(url, params=None):
    try:
        if _deadline.get() and time.monotonic() >= _deadline.get():
            return None
        response = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response
    except requests.RequestException:
        return None


def _json_get(url, params=None):
    response = _safe_get(url, params)
    if response is None:
        raise ValueError('Source request failed; retained previous listings')
    return response.json()


def _date(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _expired(value):
    dt = _date(value)
    return bool(dt and dt.replace(tzinfo=dt.tzinfo or timezone.utc) < datetime.now(timezone.utc))


def _row(company, title, location, department, description, url, source, published=None, size=None):
    if not url or urlparse(url).scheme != 'https' or not urlparse(url).netloc:
        raise ValueError('Source omitted a valid job URL')
    evidence = extract_eligibility(description)
    return {
        'company': company, 'role': title, 'field': _classify_field(title, department) or 'Operations',
        'city': location, 'description': plain_text(description), 'duration': None,
        'deadline': 'Listed on employer feed; check application requirements',
        'url': url, 'source': source, 'company_size': size, 'published_at': _date(published),
        'opportunity_type': 'expression_of_interest' if re.search(r'expression of interest|rolling intake|talent pool', title, re.I) else 'internship' if re.search(r'intern|vacation|studentship', title, re.I) else 'graduate',
        'eligibility_source_url': url if evidence['eligibility_evidence'] else None,
        **evidence,
    }


def scrape_greenhouse_board(board_token, display_name, company_size=None):
    try:
        data = _json_get(f'https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs', {'content': 'true'})
        if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
            raise ValueError('Unexpected Greenhouse response')
        rows = []
        for job in data['jobs']:
            title, location = job.get('title', ''), (job.get('location') or {}).get('name', '')
            if not _title_matches_intern_or_grad(title) or not _location_is_australian(location):
                continue
            department = ', '.join(d.get('name', '') for d in job.get('departments', []))
            if _classify_field(title, department) is None:
                continue
            rows.append(_row(display_name, title, location, department, job.get('content', ''), job.get('absolute_url'), f'greenhouse:{board_token}', size=company_size))
        return SourceRows(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return SourceRows(status='error', message=str(exc))


def scrape_lever_board(board_token, display_name, company_size=None):
    try:
        data = _json_get(f'https://api.lever.co/v0/postings/{board_token}', {'mode': 'json'})
        if not isinstance(data, list):
            raise ValueError('Unexpected Lever response')
        rows = []
        for job in data:
            title, categories = job.get('text', ''), job.get('categories') or {}
            location = categories.get('location', '')
            if not _title_matches_intern_or_grad(title) or not _location_is_australian(location, job.get('country')):
                continue
            department = categories.get('team', '') or categories.get('department', '')
            description = job.get('descriptionPlain') or job.get('description') or ''
            description += '\n' + (job.get('additionalPlain') or job.get('additional') or '')
            for section in job.get('lists', []) or []:
                description += '\n' + section.get('text', '') + '\n' + section.get('content', '')
            rows.append(_row(display_name, title, location, department, description, job.get('hostedUrl'), f'lever:{board_token}', size=company_size))
        return SourceRows(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return SourceRows(status='error', message=str(exc))


def _kpmg_program_policy():
    url = 'https://kpmg.com/au/en/careers/graduates/faq.html'
    response = _safe_get(url)
    if response is None:
        return None
    text = plain_text(response.text)
    # Only program eligibility paragraphs; unrelated FAQs cannot override a role.
    paragraphs = [p for p in text.splitlines() if ('welcome applications' in p.lower() and 'international students' in p.lower()) or ('full-time working rights' in p.lower() and 'program dates' in p.lower())]
    evidence = extract_eligibility('\n'.join(paragraphs))
    return {**evidence, 'eligibility_source_url': url} if evidence['accepts_international'] is True else None


def scrape_smartrecruiters_board(board_token, display_name, company_size=None):
    rows, failed_details = [], 0
    try:
        base = f'https://api.smartrecruiters.com/v1/companies/{board_token}/postings'
        jobs, seen = [], set()
        for offset in range(0, 10000, 100):
            data = _json_get(base, {'country': 'au', 'limit': 100, 'offset': offset})
            if not isinstance(data, dict) or not isinstance(data.get('content'), list) or not isinstance(data.get('totalFound'), int):
                raise ValueError('Unexpected SmartRecruiters response')
            page = data['content']
            for job in page:
                if job['id'] not in seen:
                    jobs.append(job)
                    seen.add(job['id'])
            if offset + len(page) >= data['totalFound']:
                break
            if not page:
                raise ValueError('Incomplete source pagination')
        else:
            raise ValueError('Source pagination limit reached')
        policy = None
        for job in jobs:
            title, location = job.get('name', ''), job.get('location') or {}
            if not _title_matches_intern_or_grad(title) or not _location_is_australian(location.get('fullLocation', ''), location.get('country')):
                continue
            try:
                detail = _json_get(f"{base}/{job['id']}")
                if not isinstance(detail, dict) or 'active' not in detail:
                    raise ValueError('Missing posting status')
                if detail['active'] is not True or detail.get('visibility', 'PUBLIC') != 'PUBLIC' or _expired(detail.get('validThrough')):
                    continue
                sections = detail['jobAd']['sections']
                description = '\n'.join(s.get('text', '') for s in sections.values() if isinstance(s, dict))
                department = (detail.get('function') or {}).get('label', '')
                row = _row(display_name, title, location.get('fullLocation') or location.get('city') or 'Australia', department, description, detail.get('postingUrl'), f'smartrecruiters:{board_token}', detail.get('releasedDate'), company_size)
                if board_token == 'KPMGAustralia1' and re.search(r'KPMG (?:Graduate|Vacationer)', title, re.I) and row['accepts_international'] is None:  # nosec B105 — this is KPMG's public SmartRecruiters company slug (visible in their own careers URL), not a credential
                    if policy is None:
                        policy = _kpmg_program_policy() or {}
                    if policy:
                        row.update(policy)
                rows.append(row)
            except (ValueError, TypeError, KeyError):
                failed_details += 1
        return SourceRows(rows, 'partial' if failed_details else 'ok', f'{failed_details} job details unavailable' if failed_details else None)
    except (ValueError, TypeError, KeyError) as exc:
        return SourceRows(rows, 'error', str(exc))


class _CareerHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.scripts, self._script = set(), [], None
        self.titles, self._link, self._title = {}, None, ''
        self.pagination, self.micro, self._stack = set(), {}, []
        self.has_job_schema, self.has_apply = False, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.has_job_schema |= 'schema.org/JobPosting' in attrs.get('itemtype', '')
        if tag == 'a' and '/talentcommunity/apply/' in attrs.get('href', ''):
            self.has_apply = True
        if tag == 'a' and 'startrow=' in attrs.get('href', ''):
            self.pagination.add(attrs['href'])
        prop = attrs.get('itemprop')
        if prop in ('title', 'description', 'streetAddress', 'datePosted', 'validThrough'):
            if 'content' in attrs:
                self.micro.setdefault(prop, []).append(attrs['content'])
        else:
            prop = self._stack[-1][1] if self._stack else None
        if tag not in ('meta', 'br', 'hr', 'img', 'input', 'link', 'source', 'wbr', 'area', 'base', 'embed'):
            self._stack.append((tag, prop))
        if tag == 'a' and '/job/' in attrs.get('href', ''):
            self.links.add(attrs['href'])
            self._link, self._title = attrs['href'], ''
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self._script = ''

    def handle_data(self, data):
        if self._stack and self._stack[-1][1]:
            self.micro.setdefault(self._stack[-1][1], []).append(data)
        if self._link is not None:
            self._title += data
        if self._script is not None:
            self._script += data

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                if tag in ('p', 'li', 'div') and self._stack[i][1]:
                    self.micro.setdefault(self._stack[i][1], []).append('\n')
                del self._stack[i:]
                break
        if tag == 'a' and self._link is not None:
            if self._title.strip():
                self.titles[self._link] = self._title.strip()
            self._link = None
        if tag == 'script' and self._script is not None:
            self.scripts.append(self._script)
            self._script = None


def scrape_csiro():
    rows = []
    try:
        pending = ['https://jobs.csiro.au/go/Students/990500/']
        visited, titles, links = set(), {}, set()
        pages = 1
        while pending:
            page_url = pending.pop()
            if page_url in visited:
                continue
            if len(visited) >= 20:
                raise ValueError('CSIRO pagination limit reached')
            response = _safe_get(page_url)
            if response is None:
                raise ValueError('CSIRO search unavailable')
            visited.add(page_url)
            parser = _CareerHTML()
            parser.feed(response.text)
            page_match = re.search(r'Page\s+\d+\s+of\s+(\d+)', plain_text(response.text), re.I)
            if not page_match:
                raise ValueError('CSIRO results structure changed')
            pages = max(pages, int(page_match[1]))
            titles.update(parser.titles)
            links.update(parser.links)
            for href in parser.pagination:
                target = urljoin(page_url, href)
                parsed = urlparse(target)
                if parsed.scheme == 'https' and parsed.netloc == 'jobs.csiro.au' and parsed.path.startswith('/go/Students/990500/') and target not in visited:
                    pending.append(target)
        if len(visited) < pages:
            raise ValueError('CSIRO pagination incomplete')
        for href in links:
            if href not in titles:
                raise ValueError('CSIRO job title missing')
            if not _title_matches_intern_or_grad(titles[href]):
                continue
            url = urljoin('https://jobs.csiro.au', href)
            if urlparse(url).netloc != 'jobs.csiro.au':
                continue
            detail = _safe_get(url)
            if detail is None:
                raise ValueError('CSIRO job detail unavailable')
            page = _CareerHTML()
            page.feed(detail.text)
            found = False
            # SuccessFactors currently publishes schema.org microdata, not JSON-LD.
            if page.has_job_schema and page.micro:
                found = True
                fields = {key: ''.join(value).strip() for key, value in page.micro.items()}
                title, location = fields.get('title', ''), fields.get('streetAddress', '')
                if not title or not fields.get('description'):
                    raise ValueError('CSIRO job microdata incomplete')
                if page.has_apply and _title_matches_intern_or_grad(title) and _location_is_australian(location) and not _expired(fields.get('validThrough')):
                    row = _row('CSIRO', title, location, 'Research', fields['description'], url, 'csiro')
                    try:
                        row['published_at'] = datetime.strptime(fields.get('datePosted', ''), '%a %b %d %H:%M:%S UTC %Y').replace(tzinfo=timezone.utc)
                    except ValueError:
                        row['published_at'] = _date(fields.get('datePosted'))
                    rows.append(row)
                continue
            for script in page.scripts:
                data = json.loads(script)
                objects = data if isinstance(data, list) else data.get('@graph', [data])
                for job in objects:
                    if job.get('@type') != 'JobPosting':
                        continue
                    found = True
                    title = job.get('title', '')
                    if not _title_matches_intern_or_grad(title) or _expired(job.get('validThrough')):
                        continue
                    locations = job.get('jobLocation', {})
                    addresses = [loc.get('address', {}) for loc in (locations if isinstance(locations, list) else [locations])]
                    au = [a for a in addresses if _location_is_australian('', a.get('addressCountry'))]
                    if au:
                        rows.append(_row('CSIRO', title, ', '.join(a.get('addressLocality', 'Australia') for a in au), 'Research', job.get('description', ''), url, 'csiro', job.get('datePosted')))
            if not found:
                raise ValueError('CSIRO structured job detail unavailable')
        return SourceRows(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return SourceRows(rows, 'partial' if rows else 'error', str(exc))


def run_all_scrapers():
    deadline_token = _deadline.set(time.monotonic() + 15 * 60)
    batch = ScrapeBatch()
    adapters = {'greenhouse': scrape_greenhouse_board, 'lever': scrape_lever_board, 'smartrecruiters': scrape_smartrecruiters_board}
    for board in COMPANY_BOARDS + [{'platform': 'csiro', 'token': '', 'display_name': 'CSIRO'}]:
        source = f"{board['platform']}:{board['token']}" if board['token'] else 'csiro'
        try:
            rows = scrape_csiro() if source == 'csiro' else adapters[board['platform']](board['token'], board['display_name'], board.get('company_size'))
            batch.extend(rows)
            batch.reports[source] = {'status': getattr(rows, 'status', 'ok'), 'message': getattr(rows, 'message', None), 'count': len(rows)}
        except Exception as exc:
            batch.reports[source] = {'status': 'error', 'message': f'Source failed ({type(exc).__name__})', 'count': 0}
        print(f"[scraper] {source}: {batch.reports[source]}")
    _deadline.reset(deadline_token)
    return batch


def apply_scrape_results(db, scraped):
    from .models import Internship, ListingStatus, DiscoverySource
    now = datetime.now(timezone.utc)
    added, updated, seen = 0, 0, {}
    for row in scraped:
        row = dict(row)
        source = row.get('source')
        seen.setdefault(source, set()).add(row['url'])
        existing = db.query(Internship).filter(Internship.url == row['url']).first()
        if existing:
            for key, value in row.items():
                setattr(existing, key, value)
            existing.scraped_at, existing.source_active = now, True
            updated += 1
        else:
            db.add(Internship(**row, scraped_at=now, first_seen_at=now, source_active=True, status=ListingStatus.approved))
            added += 1
    for source, report in getattr(scraped, 'reports', {}).items():
        record = db.get(DiscoverySource, source)
        if record is None:
            record = DiscoverySource(source=source)
            db.add(record)
        record.status, record.message = report['status'], report.get('message')
        record.checked_at, record.count = now, report['count']
        if report['status'] == 'ok':
            record.last_success_at = now
            q = db.query(Internship).filter(Internship.source == source)
            if seen.get(source):
                q = q.filter(Internship.url.notin_(seen[source]))
            q.update({'source_active': False}, synchronize_session=False)
    return added, updated

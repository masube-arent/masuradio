import asyncio, calendar, concurrent.futures, datetime as dt, json, os, re, subprocess, tempfile, time
from pathlib import Path
import requests, feedparser, edge_tts
try:
    from scripts import story_quality, stage_resume, editorial
except ModuleNotFoundError:
    import story_quality, stage_resume, editorial
# MASURADIO-EVIDENCE-RESUME-V1

ROOT=Path(__file__).resolve().parents[1]
EP=ROOT/'episodes'
EP.mkdir(exist_ok=True)
JST=dt.timezone(dt.timedelta(hours=9))
TODAY=dt.datetime.now(JST).date().isoformat()
VOICES={'NANA':'ja-JP-NanamiNeural'}
TTS_RATE='+0%'  # Natural speed; the previous +8% could sound hurried.
# Diverse, official RSS/Atom sources. Failures of individual feeds are non-fatal.
FEEDS=[
    ('OpenAI','https://openai.com/news/rss.xml'),
    ('Google AI','https://blog.google/technology/ai/rss/'),
    ('DeepMind','https://deepmind.google/blog/rss.xml'),
    ('Hugging Face','https://huggingface.co/blog/feed.xml'),
    ('Google Developers','https://developers.googleblog.com/feeds/posts/default?alt=rss'),
    ('Microsoft AI','https://www.microsoft.com/en-us/ai/blog/feed'),
    ('GitHub AI','https://github.blog/ai-and-ml/feed/'),
    ('GitHub','https://github.blog/changelog/feed/'),
    ('Codex','https://github.com/openai/codex/releases.atom'),
    ('Claude Code','https://github.com/anthropics/claude-code/releases.atom'),
]

# One distinct editorial pillar per weekday; news supports the pillar, not vice versa.
SHOWS=[
    ('月曜：AIモデル・研究の最前線',
     'モデルの進化、オープンモデル、研究成果を一般の人にも分かるように説明する。',
     r'model|benchmark|reasoning|research|paper|science|training|open.weight|llm|gemini|gpt|mistral|llama'),
    ('火曜：使えるAIサービス・仕事術',
     '最新のAIアプリ、日常・仕事での活用、業務を楽にする具体例。コーディングツールだけに限定しない。',
     r'app|product|tool|copilot|workspace|office|search|workflow|productivity|business|chatgpt|assistant'),
    ('水曜：自動化・AIエージェント実験室',
     'エージェントやAPI連携で繰り返し作業を自動化する。実装と失敗例を掘り下げる。',
     r'agent|automation|workflow|sdk|api|codex|claude.code|orchestrat|tool.call|mcp'),
    ('木曜：画像・音声・動画の世界',
     '画像生成、動画制作、音声、マルチモーダル、UIや創作などの話題を主役にする。',
     r'video|audio|image|speech|voice|music|multimodal|vision|photo|creative|visual|diffusion'),
    ('金曜：AIの安全性・品質・お金',
     'ハルシネーション、セキュリティ、評価、権限、推論コスト、運用事故を実例で説明する。',
     r'safety|security|evaluation|eval|privacy|trust|attack|cost|pricing|governance|policy|risk'),
    ('土曜：週末のAIおもしろ実験',
     'ロボット、ゲーム、趣味のプロダクト、変わったアイデア、試作や創作を楽しく掘り下げる。',
     r'robot|game|experiment|prototype|demo|open.source|creative|simulation|research|build'),
    ('日曜：AIが変える暮らしと仕事',
     '医療、教育、科学、企業や生活での実例と今後の変化。週のニュース再放送にはしない。',
     r'education|health|science|customer|business|enterprise|real.world|society|impact|case.study'),
]


# Pronunciation dictionary used only for speech synthesis, not for saved scripts.
# Claude Code can be misread as "クローダーコード" by the Japanese TTS voice.
_TTS_READINGS = (
    (re.compile(r'(?<![A-Za-z])Claude[ \\t\\u3000・_-]*Code(?![A-Za-z])', re.IGNORECASE), 'クロードコード'),
    (re.compile(r'クローダー[・ ]?コード'), 'クロードコード'),
)


def tts_text(text):
    """Replace ambiguous product names with their intended Japanese readings."""
    for pattern, reading in _TTS_READINGS:
        text = pattern.sub(reading, text)
    return text


def read_feed(name, url):
    try:
        response=requests.get(url,timeout=12,headers={'User-Agent':'MASURADIO/1.0'})
        response.raise_for_status()
        feed=feedparser.parse(response.content)
        result=[]
        for entry in feed.entries[:25]:
            stamp=entry.get('published_parsed') or entry.get('updated_parsed')
            if not stamp:
                continue
            date=dt.datetime.fromtimestamp(calendar.timegm(stamp),dt.timezone.utc)
            age=dt.datetime.now(dt.timezone.utc)-date
            if not -dt.timedelta(hours=12)<=age<=dt.timedelta(days=14):
                continue
            title=re.sub(r'\s+',' ',entry.get('title','')).strip()
            url=entry.get('link','')
            if not title or not url:
                continue
            # Ignore prerelease churn that drowned out actual AI news.
            if name in ('Codex','Claude Code') and re.search(r'(?:alpha|beta|rc\d*|nightly|preview)',title,re.I):
                continue
            summary=re.sub('<[^>]*>',' ',entry.get('summary',''))
            result.append({'source':name,'title':title[:160],'url':url,
                           'date':date.date().isoformat(),
                           'summary':re.sub(r'\s+',' ',summary)[:550]})
            if len(result)>=4:
                break
        return result
    except (requests.RequestException,ValueError,TypeError,OverflowError) as error:
        print(f'Feed unavailable: {name}: {type(error).__name__}',flush=True)
        return []


def news():
    # Fetch feeds in parallel so one slow publisher cannot delay every broadcast.
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        batches=list(pool.map(lambda row:read_feed(*row),FEEDS))
    items=[]
    seen=set()
    # Round-robin by publisher, not a flood of version tags from one repository.
    for index in range(4):
        for batch in batches:
            if index>=len(batch):
                continue
            item=batch[index]
            key=item['url'].rstrip('/').lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    print(f'Collected {len(items)} unique stories from {sum(bool(x) for x in batches)} feeds',flush=True)
    return items


def episode_history(base=EP):
    history=[]
    for file in sorted(base.glob('????-??-??.json'),reverse=True)[:7]:
        try:
            past=json.loads(file.read_text(encoding='utf-8'))
            # Older episodes did not track featured sources, only collected sources.
            used=past.get('featured_sources') or past.get('sources',[])[:3]
            history.append({'date':past.get('date'),'title':past.get('title',''),
                            'topics':past.get('topics',[]),
                            'used_urls':[item.get('url') for item in used if isinstance(item,dict)]})
        except (ValueError,OSError,TypeError):
            continue
    return history


def select_sources(items, focus_keyword, history, limit=8):
    """Give relevant stories space, but prioritize variety and avoid recycled coverage."""
    used={url for episode in history[:5] for url in episode.get('used_urls',[]) if url}
    counts={}
    for episode in history[:5]:
        for url in episode.get('used_urls',[]):
            counts[url]=counts.get(url,0)+1
    pattern=re.compile(focus_keyword,re.I)
    candidates=sorted(items,key=lambda item:(
        item.get('url') in used,
        not bool(pattern.search(item.get('title','')+' '+item.get('summary',''))),
        -(int(item.get('date','1970-01-01').replace('-','') or '19700101')),
        item.get('source','')))
    chosen=[]
    publisher_counts={}
    # Reserve up to half for the current editorial topic, remainder for other fields.
    on_topic=[item for item in candidates if pattern.search(item.get('title','')+' '+item.get('summary',''))]
    other=[item for item in candidates if item not in on_topic]
    def take(pool, quota):
        for item in pool:
            if len(chosen)>=quota:
                break
            source=item['source']
            if publisher_counts.get(source,0)>=2 or item in chosen:
                continue
            chosen.append(item)
            publisher_counts[source]=publisher_counts.get(source,0)+1
    take(on_topic,limit//2)
    take(other,limit)
    take(candidates,limit)
    # If feed availability is limited, still make a show using timeless examples.
    return chosen


def request_gemini(prompt, key, model, thinking_budget=512, max_output_tokens=8192, temperature=0.7):
    """Cap Gemini 2.5 Flash thinking so the JSON script is not cut off.

    Gemini counts hidden thought tokens toward maxOutputTokens. Keep some
    thinking for the first attempt; retries can disable it entirely.
    """

    retryable_status = {429, 500, 502, 503, 504}
    for attempt in range(5):
        delay = min(30, 2 ** (attempt + 1))
        try:
            config = {'responseMimeType': 'application/json',
                      'maxOutputTokens': max_output_tokens, 'temperature': temperature}
            # thinkingBudget applies to Gemini 2.5; other model series may
            # require thinkingLevel or reject this field entirely.
            if model.startswith('gemini-2.5'):
                config['thinkingConfig'] = {'thinkingBudget': thinking_budget}
            response = requests.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                params={'key': key},
                json={'contents': [{'parts': [{'text': prompt}]}],
                      'generationConfig': config},
                timeout=(15, 180))
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status not in retryable_status or attempt == 4:
                raise
            retry_after = error.response.headers.get('Retry-After', '')
            try:
                delay = min(60, max(delay, float(retry_after)))
            except ValueError:
                pass
            print(f'Gemini transient HTTP {status}; retry {attempt+2}/5 in {delay}s', flush=True)
        except (requests.Timeout, requests.ConnectionError, ValueError) as error:
            if attempt == 4:
                raise
            print(f'Gemini transient {type(error).__name__}; retry {attempt+2}/5 in {delay}s', flush=True)
        time.sleep(delay)
    raise RuntimeError('Gemini API retries exhausted')


def validate_segments(segments):
    """Require a single female DJ: never synthesize another speaker."""
    if not isinstance(segments,list) or len(segments)<6:
        raise ValueError('Too few solo DJ segments')
    for segment in segments:
        if (not isinstance(segment,dict)
                or segment.get('speaker')!='NANA'
                or not isinstance(segment.get('text'),str)
                or not 5<=len(segment['text'])<=500):
            raise ValueError('Invalid solo DJ segment')
    return segments

def write_script(items, stage=None):
    """Write distinct verified chapters and checkpoint each successful Gemini part."""
    history = episode_history()
    focus, show_direction, focus_keyword = SHOWS[dt.datetime.now(JST).weekday()]
    selected = select_sources(story_quality.group_stories(items), focus_keyword, history)
    # Collect article text from a bounded shortlist, never entire sites.
    if stage:
        reviewed, _ = stage.json(
            'article_evidence', {'stories': selected, 'fetch_version': 'v2'},
            lambda: story_quality.collect_evidence(selected),
            lambda value: isinstance(value, list) and all(
                isinstance(x, dict) and x.get('evidence_status') in
                ('body', 'summary_only') for x in value))
    else:
        reviewed = story_quality.collect_evidence(selected)
    featured = story_quality.group_stories(reviewed)
    verified = [x for x in featured if x.get('evidence_status') == 'body']
    brief = [x for x in featured if x.get('evidence_status') != 'body']
    print(f'Evidence: {len(verified)} body-confirmed; {len(brief)} headline-only', flush=True)

    topics = editorial.plan_chapters(featured)
    labels = [chapter[0] for chapter in topics]

    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise RuntimeError('GEMINI_API_KEY secret is missing')
    model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    all_segments, part_starts = [], []
    usage = {'prompt_tokens': 0, 'output_tokens': 0, 'thinking_tokens': 0,
             'total_tokens': 0, 'api_calls': 0}
    title = None
    drafts = []
    for number, (topic, role, sources) in enumerate(topics, 1):
        prompt = editorial.chapter_prompt(TODAY, number, topics, focus, show_direction,
                                          history, all_segments)

        def produce_part():
            part_usage = {'prompt_tokens': 0, 'output_tokens': 0,
                          'thinking_tokens': 0, 'total_tokens': 0, 'api_calls': 0}
            if role == 'brief':
                part = editorial.brief_draft(TODAY, sources, focus,
                                            has_report=any(c[1] == 'report' for c in topics))
                validate_segments(part['segments'])
                editorial.validate_editorial(part, sources, all_segments, number, role, TODAY)
                return {**part, 'usage': part_usage}
            feedback = ''
            for attempt in range(3):
                budget, limit = (512, 8192) if attempt == 0 else (0, 12288)
                result = request_gemini(prompt + feedback, key, model, thinking_budget=budget,
                                        max_output_tokens=limit)
                met = result.get('usageMetadata', {})
                part_usage['api_calls'] += 1
                for field, src in (('prompt_tokens', 'promptTokenCount'),
                                   ('output_tokens', 'candidatesTokenCount'),
                                   ('thinking_tokens', 'thoughtsTokenCount'),
                                   ('total_tokens', 'totalTokenCount')):
                    part_usage[field] += int(met.get(src, 0) or 0)
                candidate = (result.get('candidates') or [{}])[0]
                finish = candidate.get('finishReason', 'UNKNOWN')
                raw = ''.join(x.get('text', '') for x in
                              candidate.get('content', {}).get('parts', []))
                try:
                    if finish not in ('STOP', 'UNKNOWN'):
                        raise ValueError(f'Gemini finish reason: {finish}')
                    parsed = json.loads(raw)
                    segments = validate_segments(parsed['segments'])
                    editorial.validate_editorial(parsed, sources, all_segments, number, role, TODAY)
                    return {'segments': segments, 'episode_title': parsed.get('episode_title', ''),
                            'claims': parsed['claims'], 'practice': parsed.get('practice'),
                            'usage': part_usage}
                except (ValueError, TypeError, KeyError) as error:
                    feedback = f'\nPrevious draft rejected: {error}. Correct this and return complete JSON.'
                    print(f'Part {number}, attempt {attempt+1}/3: {error}', flush=True)
                    if attempt == 2:
                        raise RuntimeError(f'Could not generate part {number}') from error
                    time.sleep(2 * (attempt+1))
            raise RuntimeError('Unreachable generation failure')

        def valid_part(part):
            try:
                validate_segments(part['segments'])
                editorial.validate_editorial(part, sources, all_segments, number, role, TODAY)
                return isinstance(part.get('usage'), dict)
            except (TypeError, KeyError, ValueError):
                return False

        if stage:
            part, reused = stage.json(
                f'script_part_{number}',
                {'prompt': prompt, 'model': model, 'temperature': 0.7,
                 'editorial_version': editorial.VERSION,
                 'thinking_budget': (512, 0), 'output_tokens': (8192, 12288)},
                produce_part, valid_part)
        else:
            part, reused = produce_part(), False
        drafts.append(part)
        part_starts.append(len(all_segments))
        all_segments.extend(part['segments'])
        if number == 1 and isinstance(part.get('episode_title'), str):
            title = part['episode_title'].strip() or None
        for field in usage:
            usage[field] += part['usage'].get(field, 0)
        print(f'Part {number}/{len(topics)}: {len(part["segments"])} segments '
              f'({"reused" if reused else "new"})', flush=True)
    # One cached, bounded semantic audit before any TTS or publication. A failure
    # preserves stage caches but stops production rather than broadcasting guesses.
    audit_input = editorial.audit_prompt(drafts, topics)
    def produce_audit():
        result = request_gemini(audit_input, key, model, thinking_budget=512,
                                max_output_tokens=4096, temperature=0.1)
        candidate = (result.get('candidates') or [{}])[0]
        if candidate.get('finishReason', 'UNKNOWN') not in ('STOP', 'UNKNOWN'):
            raise RuntimeError('Editorial audit response incomplete')
        try:
            raw = ''.join(x.get('text', '') for x in candidate.get('content', {}).get('parts', []))
            decision = json.loads(raw)
            if (not isinstance(decision, dict) or type(decision.get('approved')) is not bool
                    or not isinstance(decision.get('issues'), list)
                    or any(not isinstance(x, str) for x in decision['issues'])):
                raise ValueError('Invalid audit decision')
        except (ValueError, TypeError) as error:
            raise RuntimeError('Editorial audit returned invalid JSON') from error
        return {**decision, 'usage': result.get('usageMetadata', {})}
    if stage:
        audit, _ = stage.json('editorial_audit', {'prompt': audit_input, 'model': model,
                              'version': editorial.VERSION, 'temperature': 0.1}, produce_audit,
                              lambda x: isinstance(x, dict) and type(x.get('approved')) is bool
                              and isinstance(x.get('issues'), list)
                              and all(isinstance(issue, str) for issue in x['issues'])
                              and isinstance(x.get('usage'), dict))
    else:
        audit = produce_audit()
    if not audit['approved'] or audit['issues']:
        raise RuntimeError('Editorial audit rejected episode: ' + '; '.join(audit['issues']))
    usage['api_calls'] += 1
    for field, src in (('prompt_tokens', 'promptTokenCount'),
                       ('output_tokens', 'candidatesTokenCount'),
                       ('thinking_tokens', 'thoughtsTokenCount'), ('total_tokens', 'totalTokenCount')):
        usage[field] += int(audit['usage'].get(src, 0) or 0)
    usage['estimated_usd'] = round((usage['prompt_tokens']*0.30+
                                    (usage['output_tokens']+usage['thinking_tokens'])*2.50)
                                   / 1_000_000, 6)
    return all_segments, usage, focus, title, featured, part_starts, labels

async def render(segments, tmp, stage=None):
    paths, durations = [], []
    for i, segment in enumerate(segments):
        spoken = tts_text(segment['text'])
        voice = VOICES[segment['speaker']]
        async def synthesize(target, text=spoken, voice_name=voice, index=i):
            for attempt in range(6):
                try:
                    print(f'TTS segment={index}, attempt={attempt+1}', flush=True)
                    await edge_tts.Communicate(text, voice_name, rate=TTS_RATE).save(str(target))
                    if target.stat().st_size < 100:
                        raise RuntimeError('Empty audio')
                    return
                except Exception as error:
                    target.unlink(missing_ok=True)
                    if attempt == 5:
                        raise
                    print(f'TTS retry {index}: {type(error).__name__}', flush=True)
                    await asyncio.sleep(3 * (attempt+1))
        if stage:
            path, seconds, _ = await stage.audio(spoken, voice, TTS_RATE, synthesize)
        else:
            path = tmp / f'{i:03}.mp3'
            await synthesize(path)
            seconds = stage_resume.probe_audio(path)
            if seconds is None:
                raise RuntimeError(f'Unplayable TTS segment {i}')
        paths.append(path)
        durations.append(seconds)

    def make_mp3(target):
        # paths are absolute when cached; -safe 0 permits FFmpeg concat paths.
        concat = tmp / 'concat.txt'
        def quote(p):
            return str(p.resolve()).replace("'", "'\\\\''")
        concat.write_text(''.join("file '" + quote(p) + "'\n" for p in paths), encoding='utf-8')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'concat', '-safe', '0', '-i', str(concat),
                        '-c:a', 'libmp3lame', '-b:a', '64k', str(target)], check=True)
        original = stage_resume.probe_audio(target)
        if original is None:
            raise RuntimeError('Merged audio could not be decoded')
        fit_duration(target, round(original))

    if stage:
        output, seconds, _ = stage.file('final_audio',
                                       {'segments': [stage_resume.digest({
                                           'text': tts_text(x['text']),
                                           'voice': VOICES[x['speaker']],
                                           'rate': TTS_RATE}) for x in segments],
                                        'ffmpeg': 'libmp3lame-64k'}, make_mp3)
    else:
        output = tmp / f'{TODAY}.mp3'
        make_mp3(output)
        seconds = stage_resume.probe_audio(output)
    if seconds is None:
        raise RuntimeError('Final episode audio invalid')
    return output, round(seconds), durations

def fit_duration(audio, duration):
    """Aim for 10-20 minutes without rejecting a valid, complete broadcast."""
    if duration <= 0:
        raise RuntimeError('Generated audio has zero duration')
    if duration > 1200:
        # Preserve all speech and its pitch. Do not make listeners endure extreme speedups.
        factor = min(duration / 1190, 1.25)
        adjusted = audio.with_name(audio.stem + '.adjusted.mp3')
        try:
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', str(audio), '-filter:a', f'atempo={factor:.5f}',
                            '-c:a', 'libmp3lame', '-b:a', '64k', str(adjusted)], check=True)
            adjusted.replace(audio)
        finally:
            adjusted.unlink(missing_ok=True)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)],
                               check=True, capture_output=True, text=True)
        duration = round(float(probe.stdout.strip()))
        print(f'Adjusted episode tempo to {factor:.3f}x; duration={duration}s', flush=True)
    if not 600 <= duration <= 1200:
        print(f'Warning: episode duration {duration}s outside preferred 10-20 min range; '
              'publishing complete audio rather than discarding it', flush=True)
    return duration

def main():
    stage = stage_resume.StageCache(ROOT / '.radio-cache', TODAY)
    items, _ = stage.json('feed_snapshot', {'day': TODAY, 'feeds': FEEDS,
                                           'collection_version': 'v1'}, news,
                          lambda v: isinstance(v, list))
    segments, usage, focus, title, featured, starts, labels = write_script(items, stage)
    with tempfile.TemporaryDirectory() as directory:
        audio, duration, measured_segments = asyncio.run(
            render(segments, Path(directory), stage))
        chapters = stage_resume.chapters_for_parts(
            starts, measured_segments, duration, labels=labels)
        sanitized = story_quality.public_sources(featured)
        metadata = {'date': TODAY, 'title': title or focus,
                    'episode_title': title or focus, 'duration_seconds': duration,
                    'audio': f'episodes/{TODAY}.mp3', 'sources': sanitized,
                    'featured_sources': sanitized, 'script': segments,
                    'chapters': chapters, 'topics': [focus], 'host': 'NANA',
                    'gemini_usage': usage}
        # Never replace a published MP3 until the new pair passes validation.
        try:
            from scripts import verify
        except ModuleNotFoundError:
            import verify
        stage_resume.verified_publish(audio, metadata, EP, TODAY, verify.check_episode)
    for old in sorted(EP.glob('????-??-??.mp3'))[:-7]:
        old.unlink(missing_ok=True)
        old.with_suffix('.json').unlink(missing_ok=True)
    print('Generated', EP / f'{TODAY}.mp3', duration)

if __name__=='__main__':
    main()



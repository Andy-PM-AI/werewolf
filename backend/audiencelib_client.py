#!/usr/bin/env python3
"""Renlab | AudienceLib 单文件 Python SDK 与可配置问卷示例（Python 3.10+，无第三方依赖）。

使用：
  1. 填写下面 API_KEY（AudienceLib 项目 Key，不是 DeepSeek / Runtime Key），
     或设置环境变量 AUDIENCELIB_KEY。不要将填写后的文件提交到公开仓库。
  2. python3 audiencelib_client.py --options  查看授权人口版本、真实筛选枚举和模型。
  3. 修改 CONFIG：国家、版本、人数、各筛选条件、模型、问卷、输出参数。
  4. python3 audiencelib_client.py            创建并保存随机人群，不调用模型；会占用抽样额度。
  5. python3 audiencelib_client.py --survey   对该人群随机 N 人发问卷，会消耗积分。
     python3 audiencelib_client.py --dry-run 仅显示请求配置，不访问网络、不占额度。

同一 STATE_FILE 中断后原命令重跑：复用人口版本、人群、选中 ID 和幂等 Key，继续查询原任务。
修改研究参数/问卷或发起新的独立研究：更换 STATE_FILE。不要删除状态文件来重试未知结果。
一个状态文件同一时间只运行一个进程；不要把别的用户的状态文件交给当前用户。
每个字段多选内部为 OR，不同字段之间为 AND；年龄包含上下限。[]/None/空字符串表示不限。
国家一次选择一个。省份在 US 对应州，在欧洲对应地区；枚举必须以 --options 为准，不能翻译。
消费领域是已有资料中的相关信号，不等于购买意愿；缺少该标签的国家/版本不能按它筛选。
全部结果是模拟人物回答，不是真人调查。unknown/refused 不能算作有效评分。
SDK 中的通用 request() 可调用全部 /v1 接口；不请求 Runtime、供应商或管理接口。
"""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

API_KEY = ""  # 用户填写自己的 al_live_...，留空时读取 AUDIENCELIB_KEY。
BASE_URL = "https://audiencelib.lifecontext.ai"
STATE_FILE = "audiencelib-client-run.json"  # 保存 ID、请求及回答，不保存 Key；新研究使用新文件。
HTTP_TIMEOUT = 30
POLL_TIMEOUT = 600  # 秒；超时不取消任务，重跑会继续等待。
POLL_INTERVAL = 2
PAGE_SIZE = 100  # 1–1000；自动读取全部页。

CONFIG = {
    "country": "CN",  # CN 中国 / US 美国 / GB 英国 / DE 德国 / FR 法国；以授权发布版本为准。
    "population_release_id": "",  # 留空选该国家默认授权版本，并保存到状态文件防止重跑换版本。
    "existing_audience_id": "",  # 填已有 aud_... 时直接使用它；不要同时设置 filters。
    "audience_name": "API 产品体验问卷",
    "size": 3,  # 创建人群人数，任意正整数但受当前可匹配人口、项目限制、剩余额度限制。
    "sampling_seed": None,  # 可选字符串；None 由服务端随机。幂等重跑靠状态文件，不靠种子。
    "filters": {
        "age": {"gte": None, "lte": None},  # 例如 18 / 60。
        "gender": "",  # 中国常见 男/女；国际常见 male/female；以枚举为准。
        "province": [],  # 例如 ["北京", "上海"]；切换国家后重新查枚举。
        "education": [],  # 例如 ["本科", "本科（在读）"]，精确拼写以 --options 为准。
        "occupation_group": [],  # 职业大类多选；具体职业文字/职业编码目前不是筛选字段。
        "urbanicity": "",  # 城乡单选，按国家人口版本枚举。
        "consumption_domains": [],  # 如 ["汽车", "电子产品"]；还有旅游出行、运动户外等，以枚举为准。
        "consumption_style": [],  # 消费风格多选，按该版本枚举；未知喜好不能自行推断。
    },
    "survey_size": 2,  # 从人群随机无放回抽 N 人答卷（1–1000，不能超过该人群人数）。
    "model": {"id": "deepseek-api", "revision": None},  # 从 /v1/models 选择；None 固定为本次可用版本。
    "protocol": {"id": "questionnaire-discrete", "version": 1},
    "parameters": {"max_tokens": 2048, "temperature": 0.7},  # 原样交给选定模型；仅填写模型支持的参数。
    "input": {
        "materials": "以下是虚构的研究材料：一款日常通勤无线耳机，售价人民币 299 元，续航 8 小时。请只根据材料及你的人物资料回答，资料不足可以回答未知。",
        "questions": [
            {"id": "interest", "type": "rating", "text": "你对这款产品有多感兴趣？1 表示完全没兴趣，5 表示非常感兴趣。", "min": 1, "max": 5, "allow_unknown": True, "allow_refused": True},
            {"id": "purchase", "type": "single_choice", "text": "你目前会考虑购买吗？", "options": ["会考虑", "不会考虑", "需要更多信息"], "allow_unknown": True, "allow_refused": True},
            {"id": "factors", "type": "multiple_choice", "text": "你最在意哪些因素？最多选两项。", "options": ["价格", "音质", "续航", "佩戴舒适度"], "min": 0, "max": 2, "allow_unknown": True, "allow_refused": True},
            {"id": "reason", "type": "text", "text": "请说明原因，不要编造材料没有提供的产品性能。", "allow_unknown": True, "allow_refused": True},
        ],
    },
    # 访谈用 protocol={"id":"interview-text","version":1}，input={"question":"请介绍你的消费习惯。"}。
    # 本示例采用 stateless，独立问卷不污染对话记忆。多轮对话请使用下方 create_session/respond 方法，
    # memory={"mode":"conversation","session_id":sid,"expected_turns":{person_id:实际 turn}}。
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 避免认证头随跨站重定向传出。


class AudienceLib:
    """可 import 使用的 SDK；方法返回服务端原始 JSON，不截断 Token 或积分精度。"""
    def __init__(self, api_key, base_url=BASE_URL, timeout=HTTP_TIMEOUT, page_size=PAGE_SIZE):
        if not api_key.strip():
            raise ValueError("请填写 API_KEY 或设置 AUDIENCELIB_KEY")
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}):
            raise ValueError("远程 API 必须使用 HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("BASE_URL 不能包含凭据、查询参数或片段")
        if not 1 <= page_size <= 1000 or timeout <= 0:
            raise ValueError("无效的分页大小或请求超时")
        self.key, self.url, self.timeout, self.page_size = api_key.strip(), base_url.rstrip('/'), timeout, page_size
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, *, idempotency_key=None):
        if not path.startswith('/v1/'):
            raise ValueError("仅允许 /v1/ 公共 API 路径")
        if method != 'GET' and not idempotency_key:
            raise ValueError("写操作需要保存并复用 idempotency_key")
        headers = {'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        last_error = None
        for attempt in range(3):
            try:
                with self.opener.open(Request(self.url + path, data=payload, headers=headers, method=method), timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                message = exc.read().decode('utf-8', errors='replace').replace(self.key, '[REDACTED]')
                last_error = RuntimeError(f'HTTP {exc.code}: {message}')
                if exc.code < 500 or attempt == 2:
                    raise last_error from None
            except (URLError, OSError) as exc:
                last_error = RuntimeError(f'Network error talking to AudienceLib: {exc}')
                if attempt == 2:
                    raise last_error from None
            time.sleep(0.6 * (attempt + 1))
        raise last_error or RuntimeError('AudienceLib request failed')

    def populations(self, country=''):
        return self.request('GET', '/v1/populations?' + urlencode({'country': country}))

    def models(self):
        return self.request('GET', '/v1/models')

    def protocols(self):
        return self.request('GET', '/v1/protocols')

    def create_audience(self, body, *, idempotency_key):
        return self.request('POST', '/v1/audiences', body, idempotency_key=idempotency_key)

    def audience(self, audience_id):
        return self.request('GET', '/v1/audiences/' + quote(audience_id, safe=''))

    def pages(self, path):
        cursor, seen = None, set()
        while True:
            query = {'page_size': self.page_size}
            if cursor:
                query['cursor'] = cursor
            result = self.request('GET', path + '?' + urlencode(query))
            yield from result['items']
            cursor = result.get('next_cursor')
            if not cursor:
                break
            if cursor in seen:
                raise RuntimeError('分页游标重复，请保留状态文件排查')
            seen.add(cursor)

    def people(self, audience_id):
        return self.pages('/v1/audiences/' + quote(audience_id, safe='') + '/people')

    def person(self, audience_id, person_id):
        return self.request('GET', '/v1/audiences/' + quote(audience_id, safe='') + '/people/' + quote(person_id, safe=''))

    def create_session(self, audience_id, body, *, idempotency_key):
        return self.request('POST', '/v1/audiences/' + quote(audience_id, safe='') + '/sessions', body, idempotency_key=idempotency_key)

    def session_people(self, session_id):
        return self.pages('/v1/sessions/' + quote(session_id, safe='') + '/people')

    def respond(self, audience_id, body, *, idempotency_key):
        return self.request('POST', '/v1/audiences/' + quote(audience_id, safe='') + '/responses', body, idempotency_key=idempotency_key)

    def job(self, job_id):
        return self.request('GET', '/v1/jobs/' + quote(job_id, safe=''))

    def results(self, job_id):
        return self.pages('/v1/jobs/' + quote(job_id, safe='') + '/results')

    def usage(self):
        return self.request('GET', '/v1/usage?scope=key')

    def credits(self):
        return self.request('GET', '/v1/credits')


def filters_from(config):
    allowed = {'age', 'gender', 'province', 'education', 'occupation_group', 'urbanicity', 'consumption_domains', 'consumption_style'}
    if set(config) - allowed:
        raise ValueError('不支持的筛选字段: ' + ', '.join(sorted(set(config) - allowed)))
    result = {k: copy.deepcopy(v) for k, v in config.items() if v not in (None, '', [])}
    if 'age' in result:
        result['age'] = {k: v for k, v in result['age'].items() if v is not None}
        if not result['age']:
            del result['age']
        elif set(result['age']) - {'gte', 'lte'} or any(type(v) is not int or v < 0 for v in result['age'].values()):
            raise ValueError('年龄使用非负整数 gte/lte')
        elif result['age'].get('gte', 0) > result['age'].get('lte', 1000000):
            raise ValueError('最低年龄不能高于最高年龄')
    for key, value in result.items():
        if key == 'age':
            continue
        if isinstance(value, list):
            if key in {'gender', 'urbanicity'} or not 1 <= len(value) <= 64 or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ValueError('无效多选值: ' + key)
        elif not isinstance(value, str) or not value.strip():
            raise ValueError('无效筛选值: ' + key)
    return result


def run(client, config, state_file=STATE_FILE, survey=False, poll_timeout=POLL_TIMEOUT, poll_interval=POLL_INTERVAL):
    config = copy.deepcopy(config)
    filters = filters_from(config['filters'])
    if type(config['size']) is not int or config['size'] < 1 or type(config['survey_size']) is not int or not 1 <= config['survey_size'] <= 1000:
        raise ValueError('size 必须为正整数；survey_size 必须为 1–1000 的整数')
    if config['existing_audience_id'] and filters:
        raise ValueError('已有的人群不能再次应用人口筛选；清空 filters 或创建新人群')
    if poll_timeout <= 0 or poll_interval <= 0:
        raise ValueError('轮询时间必须大于零')
    path = Path(state_file)
    identity = {'base_url': client.url, 'config': config}
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'run_id': str(uuid.uuid4()), 'identity': identity, 'requests': {}}
    if state['identity'] != identity:
        raise ValueError('研究参数已变更，请使用新的 STATE_FILE；不要覆盖旧任务')

    def save():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(state, out, ensure_ascii=False, indent=2)
        os.replace(temporary, path)

    def post(stage, url, body):
        if stage not in state:
            state['requests'].setdefault(stage, body)
            save()  # 写请求前先落盘。网络超时后重跑复用相同 body 和幂等 Key。
            state[stage] = client.request('POST', url, state['requests'][stage], idempotency_key=state['run_id'] + ':' + stage)
            save()
        return state[stage]

    save()
    if not state.get('audience_id'):
        if config['existing_audience_id']:
            state['audience_id'] = config['existing_audience_id']
        else:
            if 'release' not in state:
                catalog = client.populations(config['country'])
                rid = config['population_release_id'] or catalog.get('default_release_id')
                release = next((r for r in catalog['items'] if r['id'] == rid), None)
                if release is None:
                    raise ValueError('没有此国家/版本的授权；先运行 --options')
                facets = release.get('manifest', {}).get('facets', {})
                for key, value in filters.items():
                    if key != 'age' and key in facets:
                        if any(x not in facets[key] for x in (value if isinstance(value, list) else [value])):
                            raise ValueError('筛选值不在当前版本枚举内: ' + key + '；先运行 --options')
                state['release'] = rid
                save()
            sampling = {'method': 'random'}
            if config['sampling_seed'] is not None:
                sampling['seed'] = config['sampling_seed']
            result = post('audience', '/v1/audiences', {'name': config['audience_name'], 'population_release_id': state['release'], 'size': config['size'], 'filters': filters, 'sampling': sampling})
            state['audience_id'] = result['audience_id']
        save()
    aid = state['audience_id']
    if 'person_ids' not in state:
        audience = client.audience(aid)
        ids = [p['person_id'] for p in client.people(aid)]
        if len(set(ids)) != len(ids) or len(ids) != audience['size']:
            raise RuntimeError('成员页不完整或 ID 重复，未提交问卷')
        state['person_ids'] = ids
        save()
    if not survey:
        return state
    if config['survey_size'] > len(state['person_ids']):
        raise ValueError('survey_size 不能超过人群人数')
    if 'response' not in state['requests']:
        model = next((m for m in client.models()['items'] if m['id'] == config['model']['id']), None)
        if not model:
            raise ValueError('未授权该模型；请查看 --options')
        if not any(p['id'] == config['protocol']['id'] and p['version'] == config['protocol']['version'] for p in client.protocols()['items']):
            raise ValueError('不支持该协议版本；请查看 --options')
        state['selected_person_ids'] = random.SystemRandom().sample(state['person_ids'], config['survey_size'])
        state['requests']['response'] = {'target': {'person_ids': state['selected_person_ids']}, 'model': {'id': model['id'], 'revision': config['model']['revision'] or model['revision']}, 'protocol': config['protocol'], 'memory': {'mode': 'stateless'}, 'input': config['input'], 'parameters': config['parameters']}
        save()
    submission = post('response', '/v1/audiences/' + quote(aid, safe='') + '/responses', state['requests']['response'])
    deadline = time.monotonic() + poll_timeout
    while True:
        state['job'] = client.job(submission['job_id'])
        save()
        if state['job']['status'] in {'COMPLETED', 'PARTIALLY_SUCCEEDED', 'FAILED', 'CANCELLED'}:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('等待超时。保留状态文件，使用相同配置重跑继续查询，不要重新抽样')
        time.sleep(poll_interval)
    state['results'] = list(client.results(submission['job_id']))
    save()  # 先保留回答，即使随后查询账户额度失败也不丢失。
    state['key_usage_snapshot'] = client.usage()  # 整个 Key 的用量，不是单次问卷费用。
    state['credits_snapshot'] = client.credits()  # 钱包余额，不是单次问卷费用。
    save()
    if state['job']['status'] != 'COMPLETED':
        raise RuntimeError('任务结束状态 ' + state['job']['status'] + '，部分结果已保存，不自动补问失败人物')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--options', action='store_true', help='只读查看授权版本、筛选枚举、模型和协议')
    modes.add_argument('--dry-run', action='store_true', help='仅显示配置，不联网')
    modes.add_argument('--survey', action='store_true', help='创建/恢复人群并向随机 N 人提交问卷，会消耗积分')
    parser.add_argument('--state-file', default=STATE_FILE)
    args = parser.parse_args()
    try:
        if args.dry_run:
            print(json.dumps({'base_url': BASE_URL, 'config': CONFIG, 'effective_filters': filters_from(CONFIG['filters'])}, ensure_ascii=False, indent=2))
            return
        client = AudienceLib(API_KEY or os.environ.get('AUDIENCELIB_KEY', ''))
        if args.options:
            catalog = client.populations(CONFIG['country'])
            # 只输出用户需要的授权版本/枚举，不整包转储人口生产清单。
            print(json.dumps({'country': CONFIG['country'], 'default_release_id': catalog.get('default_release_id'), 'sampling_quota': catalog.get('sampling_quota'), 'limits': catalog.get('limits'), 'populations': [{'id': r['id'], 'name': r['name'], 'count': r['count'], 'country': r.get('country_code'), 'filters': r.get('manifest', {}).get('facets', {})} for r in catalog['items']], 'models': client.models(), 'protocols': client.protocols()}, ensure_ascii=False, indent=2))
            return
        state = run(client, CONFIG, args.state_file, args.survey)
        print(json.dumps({'audience_id': state['audience_id'], 'people_count': len(state['person_ids']), 'selected_person_ids': state.get('selected_person_ids'), 'job': state.get('job'), 'results': state.get('results'), 'saved_to': args.state_file}, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n保留状态文件，重试使用相同配置；更换用户或新研究请使用新文件。\n')


if __name__ == '__main__':
    main()

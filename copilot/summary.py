"""Evidence-bound handover summaries. No model, policy invention or business writes."""
import hashlib
import json
import re

from copilot.agent import positive_mention

FIELDS = ("经过概述", "诉求", "待解决", "建议")
LOCAL_SOURCE = "本地自动整理 · 待人工核对"
# These are routing aids, not an exhaustive intent classifier.
TOPICS = {
    "使用不适": ("过敏", "红肿", "刺痛", "不良反应", "医院", "就医", "起疹", "瘙痒"),
    "商品与换货": ("破损", "坏的", "按不出来", "换货", "补发", "漏发", "少件", "发错", "错发", "色差", "换！", "换!", "想退", "退换", "退了换"),
    "退款与费用": ("退款", "赔偿", "报销", "打款", "到账", "运费", "退差", "退货", "补偿"),
    "物流进度": ("物流", "快递", "签收", "没收到", "发货", "发出", "派送", "拦截", "改址", "改个地址"),
    "回访跟进": ("回访", "致电", "电话联系"),
    "商品咨询": ("套装", "赠品", "小样", "推荐", "适合", "怎么用", "区别"),
    "价格与优惠": ("降价", "价保", "保价", "优惠券", "优惠", "券", "活动价"),
    "付款咨询": ("尾款", "定金", "付款", "支付时间"),
}
ACTIONS = {
    "使用不适": "优先由专业处理人员核实并接手消费者报告的不适；查阅已提供资料，记录待补充项，不作诊断或治疗建议。",
    "商品与换货": "核对已有换货登记与实际发出记录；若已发出，核查配送及换货结果；若未确认发出，向负责换货的人员核实卡点。",
    "退款与费用": "核对各项费用的既有方案、审批和到账凭证；政策或权限不明时交有权限人员确认，不重复承诺金额或时限。",
    "物流进度": "查询对应订单的实际物流轨迹；区分原单与补发，核实发出、签收及消费者反馈是否一致。",
    "回访跟进": "核对此前约定的回访安排及实际联系记录；尚无结果时由负责跟进的人员确认下一步安排。",
    "商品咨询": "核对现有答复是否覆盖消费者的问题；未明确的商品信息查询正式资料后再反馈。",
    "价格与优惠": "核实既有优惠方案及实际履行记录；涉及价保条件或优惠权限时查询正式规则后确认。",
    "其他事项": "先依据已有沟通核实尚未明确的诉求与处理进度，再确认负责角色及可执行的下一步。",
    "付款咨询": "核对消费者已问的付款时间与可用优惠，检查客服是否逐项答复；不将条件性退订说明当作消费者退款申请。",
}
SHORT_ACTIONS = {
    "使用不适": "专业人员优先接手，核对已有资料及待补充项。",
    "商品与换货": "核对换货登记、发出及收货结果，未发出则查明卡点。",
    "退款与费用": "逐项核对方案、审批与到账凭证，未知政策先确认。",
    "物流进度": "区分原单与补发，核查实际轨迹及收货反馈。",
    "回访跟进": "核对回访承诺与联系记录，确认后续负责人。",
    "商品咨询": "核对已答复问题，缺失信息查询正式商品资料。",
    "价格与优惠": "核实优惠承诺及履行证据，未知规则先确认。",
    "其他事项": "核实当前诉求和进度，再确定下一步。",
    "付款咨询": "核对付款时间和优惠问题是否得到对应答复。",
}


def shorten(value, limit=55):
    return value if len(value) <= limit else value[:limit] + '…'


def brief_item(item):
    """A short preview; complete wording and evidence remain one click away."""
    field, topic, value = item['field'], item['topic'], item['text']
    if item.get('authored'):
        return value
    if item.get('correction'):
        return shorten(value, 90)
    if field == '建议':
        if item.get('short_action'):
            return topic + '：' + item['short_action']
        return topic + '：' + SHORT_ACTIONS.get(topic, value)
    if field == '待解决':
        if topic.startswith('记录冲突:'):
            return shorten(value, 95)
        if topic.startswith('工单核对:'):
            return '工单快照与上述实际结果仍需逐项核对。'
        if topic == '图片资料':
            return '已存在图片消息，内容未验证；勿重复笼统索要。'
        if '消费者报告结果' in value:
            return shorten(value, 70)
        return topic + '：完成证据不足，待核实。'
    if field == '经过概述' and topic not in ('起因', '最新回应'):
        if ':结果' in topic or topic.startswith('工单快照:'):
            return shorten(value, 80)
        quoted = value.split('“', 1)[-1].rsplit('”', 1)[0]
        deadlines = re.findall(r'(?:\d+(?:-\d+)?(?:个)?(?:工作日|小时|天)(?:内)?|明天上午|明天下午|今天)', quoted)
        events = [word for word in ('换货', '补发', '运费', '退款', '报销', '打款', '补偿', '券', '回访', '登记', '工单', '拦截', '改址') if word in quoted]
        return '客服记录：' + ('、'.join(events) or topic) + ('（' + '、'.join(dict.fromkeys(deadlines)) + '）' if deadlines else '') + '。'
    if field == '诉求' and '由客服处理记录提及' in value:
        return topic + '：客服提出安排，待核实接受情况。'
    if field == '诉求':
        raw = value.split('“', 1)[-1].rsplit('”', 1)[0]
        pieces = raw.split('；')
        explicit = [p for p in pieces if re.search('我要|想退|^换$|赔偿|咋|怎么|能.*吗|什么时候|啥时候', p)]
        if explicit:
            raw = explicit[-1]
        return topic + '：“' + shorten(raw, 35) + '”'
    if topic == '起因':
        raw = value.split('“', 1)[-1].rsplit('”', 1)[0]
        return '最初反馈：“' + shorten(raw, 40) + '”'
    return shorten(value, 65)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def topics(text):
    matched = {name for name, words in TOPICS.items() if any((positive_mention(text, w) if name == '使用不适' else w in text) for w in words)}
    if text.strip() == '换':
        matched.add('商品与换货')
    if '商品与换货' in matched:
        matched.discard('商品咨询')
    return matched


def clauses(text):
    return [s.strip(" ~～亲，。") for s in re.split(r"[。！？!?；;\n]|[①②③④⑤]", text) if s.strip(" ~～亲，。")]


def concise(messages, topic, buyer_only=False):
    parts = []
    for m in messages:
        if buyer_only and m["角色"] != "买家":
            continue
        for s in clauses(m["message_text"]):
            if topic == "其他事项" or topic in topics(s):
                if s not in parts:
                    parts.append(s)
    return parts


def build_summary(cases, snapshots=None, selections=None):
    """cases[0] is primary; linked cases are limited to confirmed topic selections.

    Snapshots are explicitly current-only evidence supplied by the desktop. Replay
    callers omit them. Never infer completion from a ticket snapshot.
    """
    selections = selections or {}
    evidence, messages = {}, []
    for n, case in enumerate(cases):
        session = case["session_id"]
        allowed = set(selections.get(session, [])) if n else None
        for message in case["messages"]:
            if allowed is not None and not (topics(message["message_text"]) & allowed):
                continue
            m = dict(message, session=session)
            m['_topics'] = topics(m['message_text'])
            if allowed is not None:
                m['_topics'] &= allowed
            m["ref"] = session + "/" + m["message_id"]
            messages.append(m)
            evidence[m["ref"]] = {"会话": session, "时间": m["发送时间"], "角色": m["角色"], "原文": m["message_text"]}
        for kind in ("orders", "tickets"):
            for row in case[kind]:
                key = "订单号" if kind == "orders" else "工单号"
                evidence[session + "/" + row[key]] = dict(row, 来源会话=session)
    messages.sort(key=lambda m: (m["发送时间"], m["ref"]))
    # Resolve short acknowledgements only within the same session and immediate
    # explicit money context; ordinary "好的" is never completion evidence.
    for index, m in enumerate(messages):
        if index and m['角色'] == '买家' and re.search('收到了|到账了', m['message_text']) and not re.search('没|未|等|如果|希望', m['message_text']):
            previous = messages[index - 1]
            if previous['session'] == m['session'] and previous['角色'] == '客服' and re.search('退款|打款|到账', previous['message_text']):
                m['_topics'].add('退款与费用')
                m['_money_receipt'] = previous['ref']
    detected = set().union(*(m['_topics'] for m in messages)) if messages else set()
    # Only explicitly mentioned topics enter the summary; no silent classification.
    active = [name for name in TOPICS if name in detected] or ["其他事项"]
    buyer_topics = set().union(*(m['_topics'] for m in messages if m['角色'] == '买家'))
    # A service promise about warehouse receipt or a goodwill coupon is part of
    # the main resolution, not a separate buyer request for tracking, product
    # advice or a discount. Keep these topics only when the buyer raised them.
    active = [t for t in active if t not in ('物流进度', '商品咨询', '价格与优惠')
              or t in buyer_topics]
    if '商品与换货' in active:
        if '物流进度' not in buyer_topics:
            active = [t for t in active if t != '物流进度']
        if not any(re.search('退款|赔偿|报销|打款|补偿', m['message_text']) for m in messages):
            active = [t for t in active if t != '退款与费用']
        if not any('商品咨询' in m['_topics'] and re.search('怎么|适合|区别|推荐', m['message_text']) for m in messages if m['角色'] == '买家'):
            active = [t for t in active if t != '商品咨询']
    if '付款咨询' in buyer_topics and '退款与费用' not in buyer_topics:
        active = [t for t in active if t not in ('退款与费用', '物流进度')]
    if '商品与换货' in active and '退款与费用' not in buyer_topics:
        if any('两个方案' in m['message_text'] or '如果' in m['message_text'] for m in messages if m['角色'] == '客服'):
            active = [t for t in active if t != '退款与费用']
    if any('仅退款' in m['message_text'] for m in messages if m['角色'] == '买家') and '商品与换货' not in buyer_topics:
        active = [t for t in active if t != '商品与换货']
    if '退款与费用' not in buyer_topics and any('券' in m['message_text'] for m in messages):
        if not any(re.search('退款|打款|报销|到账', m['message_text']) for m in messages):
            active = [t for t in active if t != '退款与费用']
    items = []

    def add(field, key, text, refs):
        refs = list(dict.fromkeys(refs))
        items.append({"id": field + ":" + key, "field": field, "topic": key, "text": text,
                      "refs": refs, "source_hash": digest([(r, evidence[r]) for r in refs])})

    buyers = [m for m in messages if m["角色"] == "买家"]
    agents = [m for m in messages if m["角色"] == "客服"]
    if buyers:
        first = next((m for m in buyers if len(m['message_text']) > 10), buyers[0])
        add("经过概述", "起因", "消费者最初反馈：“" + first["message_text"] + "”", [first["ref"]])
    if len(buyers) > 1 and topics(buyers[-1]['message_text']):
        last = buyers[-1]
        add("经过概述", "最新回应", "消费者最新回应：“" + last["message_text"] + "”", [last["ref"]])

    for topic in active:
        relevant = [m for m in messages if topic == "其他事项" or topic in m['_topics']
                    or (topic == '商品与换货' and m['session'] == cases[0]['session_id']
                        and m['角色'] == '客服' and ('物流进度' in m['_topics'] or '运费' in m['message_text']))]
        b = [m for m in relevant if m["角色"] == "买家"]
        a = [m for m in relevant if m["角色"] == "客服"]
        refs = [m["ref"] for m in relevant]
        request = concise(b, topic, True)
        if request:
            wording = "；".join(request)
            # Preserve questions verbatim in intent instead of turning them into applications.
            add("诉求", topic, f"{topic}：消费者表述“{wording}”（按原文核实具体诉求）。", [m["ref"] for m in b])
        else:
            add("诉求", topic, f"{topic}：由客服处理记录提及；消费者是否提出或接受该项安排，需结合上下文核实。", refs)
        if topic == '商品与换货':
            # An acknowledgement belongs to the immediately preceding proposal,
            # never to a different session or to an earlier, superseded choice.
            for index, message in enumerate(messages):
                if not index or message['角色'] != '买家':
                    continue
                previous = messages[index - 1]
                if (previous['session'] == message['session'] == cases[0]['session_id']
                        and previous['角色'] == '客服'
                        and re.search('换货|补发', previous['message_text'])
                        and not re.search('退款|或者|两个方案', previous['message_text'])
                        and re.fullmatch(r'(行|好|好的|可以|同意|那行)[，,。！!\s]*(那)?(尽快|麻烦|谢谢|辛苦)?[哈呀吧了。！!\s]*', message['message_text'].strip())
                        and not any(m['角色'] == '买家' and topics(m['message_text'])
                                    for m in messages[index + 1:])):
                    add('诉求', '换货方案回应', '客服提出换货安排后，消费者回应“' + message['message_text'] + '”；后续按该安排核实进展。',
                        [previous['ref'], message['ref']])
        commitments = concise(a, topic)
        if topic == '商品与换货':
            # Keep the handover focused on substantive arrangements. Photo
            # requests remain in the timeline and the separate image limitation.
            commitments = [s for s in commitments if not re.search('麻烦拍|请拍|发张照片', s)]
            for m in a:
                commitments.extend(s for s in clauses(m['message_text']) if ('发出' in s or '运费' in s) and s not in commitments)
        if commitments:
            if topic == '商品与换货' and len(active) == 1:
                items[:] = [i for i in items if not (i['field'] == '经过概述' and i['topic'] == '起因')]
            add("经过概述", topic, f"{topic} · 客服曾说明：“{'；'.join(commitments)}”。这是沟通记录，不等同于执行凭证。", [m["ref"] for m in a])

        # Completion is deliberately claim-scoped; quoted receipt is not verified payment.
        confirmed = [m for m in b if (re.search(r"(退款|钱|款).{0,4}(已到账|到账了)|换货.{0,6}(完好|没问题)|问题.{0,3}解决了", m["message_text"]) or (topic == '退款与费用' and m.get('_money_receipt')))
                     and not re.search(r"(没|未|如果|等|希望|还没|是否)", m["message_text"])]
        if confirmed and any(m['发送时间'] > confirmed[-1]['发送时间'] and re.search('没|未|又|但是|不对', m['message_text']) for m in b):
            confirmed = []
        if topic == '退款与费用' and sum(any(w in m['message_text'] for m in relevant) for w in ('退款', '报销', '补偿', '赔偿')) > 1:
            # One receipt cannot close multiple separately promised payments.
            confirmed = []
        if confirmed:
            completion_refs = [confirmed[-1]['ref']]
            if confirmed[-1].get('_money_receipt'):
                completion_refs.append(confirmed[-1]['_money_receipt'])
            add("经过概述", topic + ':结果', f"{topic}：消费者报告结果“{confirmed[-1]['message_text']}”；这是消费者确认，不代表其他事项也已解决。", completion_refs)
        else:
            pending_text = ("换货进度待核实：是否实际发出、消费者是否收到且商品完好；客服承诺不等于发货或收货凭证。"
                            if topic == '商品与换货' else f"{topic}：尚未从所列证据确认该项完成，具体结果待核实。")
            if topic == '商品与换货' and any(re.search('寄回|退回', m['message_text']) for m in a):
                pending_text += '另需核对已提及的旧商品寄回安排是否落实。'
            add("待解决", topic, pending_text, refs)
        if confirmed:
            add('建议', topic, '保留消费者对该项结果的确认记录；如无其他未解决诉求，再由人工核实是否结束跟进。', completion_refs)
            items[-1]['short_action'] = '保留消费者确认记录，核实其他事项后再结束跟进。'
        elif topic == '物流进度' and any(re.search('拦截|改址|改个地址', m['message_text']) for m in relevant):
            add('建议', topic, '核对已提供的新地址、拦截申请和实际转寄结果；无需重复索取已提供的地址，客服称拦截成功不等于已经送达。', refs)
            items[-1]['short_action'] = '核对已有改址申请和实际转寄结果，不重复索取地址。'
        else:
            add("建议", topic, ACTIONS[topic], refs)

    images = [m for m in messages if m.get("image_path") or m.get("内容类型") == "图片"]
    if images:
        add("待解决", "图片资料", "记录中已有图片消息，不应再次笼统索要；当前未读取图片内容，无法确认图片证明了什么。", [m["ref"] for m in images])
    for session, rows in (snapshots or {}).items():
        for row in rows:
            status = row.get("任务状态", "")
            if status:
                ref = session + "/snapshot/" + row["工单号"]
                evidence[ref] = dict(row, 来源="当前工作簿快照（非历史状态）", 来源会话=session)
                negative = [m for m in buyers if m['session'] == session and re.search(r'没收到|没到账|还没|未收到|没有解决', m['message_text'])]
                if status in ('已完成', '已关闭', '已解决') and negative:
                    add('待解决', '记录冲突:' + row['工单号'], f'记录不一致：工单快照标记“{status}”，消费者曾反馈“{negative[-1]["message_text"]}”；记录时点与实际结果待核实。', [ref, negative[-1]['ref']])
                elif status in ('已完成', '已关闭', '已解决'):
                    add("待解决", "工单核对:" + row["工单号"], f"工单 {row['工单号']} 的当前快照标记“{status}”；该状态不能证明全部诉求已解决，请与消费者反馈逐项核对。", [ref])
                else:
                    add('经过概述', '工单快照:' + row['工单号'], f'当前工单快照：{status}（仅供核对，非历史状态）。', [ref])
    return {"items": items, "evidence": evidence, "topics": active,
            "timeline": [{"ref": m["ref"], **evidence[m["ref"]]} for m in messages],
            "coverage": {c["session_id"]: c["cutoff"] for c in cases},
            "fingerprint": digest([6, cases, snapshots, selections]), "version": 6}


def order_ids(provider, session):
    """Use actual order identifiers; never match on nicknames or scene labels."""
    ids = set()
    for name, frame in provider.frames.items():
        if "会话ID" not in frame:
            continue
        key = "订单号" if name == "订单" else "关联订单号"
        if key in frame:
            ids.update(x for x in frame.loc[frame["会话ID"].eq(session), key] if x)
    return ids


def candidates(provider, session):
    primary = order_ids(provider, session)
    found = []
    for other in provider.sessions():
        if other == session:
            continue
        shared = primary & order_ids(provider, other)
        if shared:
            found.append({"session": other, "orders": sorted(shared),
                          "topics": sorted(set().union(*(topics(m["message_text"]) for m in provider.messages(other))))})
    return found

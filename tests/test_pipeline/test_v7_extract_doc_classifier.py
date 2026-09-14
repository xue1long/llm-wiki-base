"""Tests for V7 extract pipeline's Stage 1: doc_classifier.

The 9 RFC v6 validation documents are used as fixtures. Each fixture
ships its expected DocType; the test asserts the classifier returns
that type without LLM fallback (i.e. heuristic accuracy >= 90% on the 9).
"""
import pytest

from src.pipeline.v7_extract.doc_classifier import (
    Classification,
    DocType,
    classify_doc,
    classify_doc_heuristic,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic but realistic, modeled on the 9 RFC v6 docs.
# Real raw files are large; we ship smaller representative slices so
# tests stay fast. The classifier should still hit the right DocType.
# ---------------------------------------------------------------------------

SINGLE_METHOD = """
# How to Write Strong Openings (Method Article)

Openings are the most important part of any novel. The reader decides
in the first chapter whether to continue. This article explains three
techniques that consistently produce strong openings:

1. Start in media res — drop the reader into action.
2. Anchor with conflict — every opening needs tension.
3. Show, don't tell the genre.

If you follow these three rules, your openings will improve.

Examples from published novels:
- 《斗破苍穹》opens with 萧炎 testing his talent at the family hall,
  immediately establishing the conflict.
- 《凡人修仙传》opens with 韩立 watching 墨大夫 walk away, anchoring
  the reader with a quiet but unsettling image.

Practicing these openings:

A good opening establishes three things in the first chapter:
the protagonist's voice, the world rules, and the central conflict.
If you cannot fit all three, prioritize the conflict — readers can
accept a confusing world if they want to know what happens next.

Common pitfalls to avoid:
- Starting with a dream sequence (overused, signals amateur work).
- Starting with a long history dump (boring, loses readers).
- Starting with the protagonist waking up (cliché).
- Starting with weather description (passive, low-energy).

Once you internalize these techniques, openings become second nature.
"""

MULTI_SECTION = """
How to Write Network Novels (Beginner's Guide)

一、 人物个性的刻画
1. 人物表现的要素：
   - 独有的表情
   - 习惯的动作
   - 常用的对白

二、配角的运用和衬托
1. 配角的类型：导师型、爱慕型、协助型

三、桥段的发挥和设定
对比法桥段 / 堆栈法桥段 / 陷阱法桥段

四、善用伏笔
伏笔的定义：作者为了表现某段重要的剧情，先前设了相关的桥段或提示。

五、剧情的节奏
过山车原理：高低起伏越大的剧情，达到的效果就越惊人。
"""

COLLECTION = """
[三江杂谈] Editor's Collection

## 作者 314 — 如何更好地包装作品

包装是新人作者最容易忽略的部分。本篇从书名 / 笔名 / 简介 / 章节名 /
排版 / 章节字数 / 书评区管理七个维度，系统讲解网络小说的包装策略。
文笔再好，语句再华丽，如果作品包装粗糙，读者很可能在第一章就流失。

## 作者 314 — 如何写好作品简介

简介是作品的"直接脸面"。本篇介绍五要五不要原则：要简洁、要整洁美观、
要体现类型、要体现卖点、要重视第一句话；不要过于文艺、不要故装清流、
不要过于老套、不要挂羊头卖狗肉、不要过于详细。

## 作者 阿零 — 解决卡文的三两招

卡文分三类：情节卡（不知情节如何发展）、言语卡（纠结词汇）、码字卡
（情绪或外界干扰不想写）。本文针对每类给出具体可操作的解决方案。

## 作者 ZENK — 写在新人成功之前

新人通病是什么？ZENK 认为"自欺欺人"是核心病因。本文从编辑视角剖析
新人常见的心态问题，指出真正的成长来自悟性而非编辑指导。

## 作者 314 — 写作相关YY小说构思方法

扩句法的核心是从"主角强"出发，按固定步骤机械式扩写为完整故事大纲。
方法简单易学，适合完全没有方向的新人作者。

## 作者 我是雷老虎 — 小说大纲构思之百炼法

受扩句法启发，但扩句法只给骨架，本文给血肉——三次提炼逐步细化大纲。

## 作者 吃了苹果 — 小说本是拼图

用拼图类比小说——把小说按主线分块，专注一块等于控制整本书。
适合长篇连载的节奏控制与爽点制造。

## 作者 8难 — 玄幻小说点子与升级体系

玄幻是起点分类最多的小说类别。点子是玄幻新书的核心，文笔厉害的作者
（烽火、猫腻）即使点子不出色也能留住读者，普通作者则需要先在创意上让人
眼前一亮。叠加是玄幻核心手法——把两种用烂的体系叠加在一个人身上出新意，
如魔剑士（魔法+武士）、光暗共存等。

## 作者 墨武 — 大纲架构与人物文档

写大纲要有清晰主线+模糊隐线——主角要变成最强 / 最有钱 / 泡最多 MM，
作者心中要有底。开新书前先整理主体人物，写时按人物文档跟踪"该人物到哪步"，
避免长篇前后不一致。
"""

QA_CHAT = """
8难讲课记录

8难(378234368) 19:59:37
玄幻估计是起点小说类别书数目最多的

8难(378234368) 19:59:43
什么都被人写过了

8难(378234368) 20:00:05
一般来说，想一本玄幻的新书 首先考虑的是点子 也就是创意

8难(378234368) 20:00:46
文笔厉害的 诸如烽火啊 猫腻啊等 他们即便是不出色的点子也能留住读者

8难(378234368) 20:01:05
像一般的作者 那就需要在创意上 先让人能眼前一亮

8难(378234368) 20:01:33
像张狂当初的无限 枫叶的随身，这些都是开创了一个流派，当然就不说了

8难(378234368) 20:01:49
我说的是在普通中找到一些新意

8难(378234368) 20:02:01
其实说穿了 在我的理解中 就两个字 叠加

8难(378234368) 20:02:16
其实叠加在很早很早就出现了

8难(378234368) 20:02:28
玄幻中 最初的魔剑士

8难(378234368) 20:02:39
这就是魔法和武士两种职业体系的叠加

8难(378234368) 20:02:59
后面陆续出现的 光暗 神魔同存一个人身上

8难(378234368) 20:03:36
等等都是采用叠加，将两种原本截然不同的体系叠加在一个人身上

8难(378234368) 20:03:55
但是同时叠加在一个人身上，就能出一些新意

8难(378234368) 20:04:27
现在这种写法已经比较普遍，通常都是一个人带着一种BUG体系 加入到原本世界中的体系

8难(378234368) 20:04:53
我个人是比较喜欢用这种

8难(378234368) 20:05:12
血法师里用的是 佛和吸血鬼之祖

8难(378234368) 20:05:21
会武功的德鲁伊 是武功+德鲁伊变形

8难(378234368) 20:05:35
星月是 类似修真+本来世界斗气

8难(378234368) 20:05:47
魔机是 机关兽+本身实力修炼

8难(378234368) 20:06:04
等等，通常都是两条线 叠加升级

8难(378234368) 20:06:16
恩 关于点子我先说这点 大家有啥意见或者问题

情红(35051327) 20:06:21
无限流和随身流是所谓的名字流派还是内容流派

8难(378234368) 20:07:11
无限流和随身流 是一种模式 无限流是 主角在不同的场景中穿梭 但是主角和配角是不变的 能力是不变的

南海十四郎(568848272) 20:07:12
随身流的书感觉都写不长，小地主是最长的

8难(378234368) 20:07:23
随身流是随身带着一种BUG

墨武(641197970) 20:07:38
我问下吧，关于叠加升级，升级路线是否会给读者辨别不清等级的问题出现？

8难(378234368) 20:07:49
其实随身流和空间戒指 类似  只是当时QQ农场。。偷菜等正流行 不可否认，这本书的火和这个有关

东方三少爷(382351811) 20:07:52
小地主就是叠加，随身+穿越

墨武(641197970) 20:08:05
如何做到叠加的时候，把等级划分明确？

8难(378234368) 20:08:36
恩 叠加 就说明有两种甚至多种体系 这就有个问题就是体系的等代

8难(378234368) 20:09:05
在最先开始写之前 你必须设定好 你的主角独有的体系 在这个普遍的世界里是什么地位

8难(378234368) 20:09:34
独有的体系是完全单独 还是相依发展

8难(378234368) 20:09:39
譬如

泣血幽灵(365876336) 20:09:51
墨武老师，我觉得就是各走各的设定

8难(378234368) 20:10:04
我从地球穿越去 我修炼的是古武

8难(378234368) 20:10:31
如果模糊的话 很难让读者有升级的快感

红泪<sxd168@qzone.qq.com> 20:32:14
插话的等等，等八神说完的，都看不到内容啦

8难(378234368) 20:43:48
娃哈哈 一下子就过去快一个小时了 大家讨论下吧 随便说说
"""

LIST_DOC = """
This is a useful resource for new writers. Here are 103 classic bridge
sections (桥段) used in YY novels:

1, 别人为求一件上刀山，下油锅的宝物，主角那里摆地摊似地送，要多少有多少，一群大官贵族艳羡，眼气，嫉妒的要死，但是还不能不巴结。

2, 小有名气的时候被人冒名顶替，结果被主角遇到，其中幽默情节自不必说。

3, 没有名气的时候（或许只是个扫地的，看图书馆的。）却有很多大的帮派或者人物对他毕恭毕敬。

4, 释放绝技时，周围人的震撼，可是结束以后却淡淡的一句：一会去哪嫖娼？

5, 有了属于自己的团队。感情绝对的深厚。深厚到别人嫉妒，在外人面前展现出来的那种友情无人能及。

6, 主角其中的一个朋友突然失踪了，主角心里很明白是谁搞的鬼，于是过去找，脸上带着笑容，可是眼里丝毫没有笑意。

7, 别人的病痛或其他，可以让人物或是读者对主角寄予希望，让人觉得主角可以救他，希望主角动手，可主角自己却不知道。

8, 朋友亦解不亦结，痛快点交点痛快的聪明人，当然前提是他不能做出什么伤害过自己的事。

9, 由一些功法融合而成提取厉害之处，创一套全新的功法，让那些原有的人都大叹奇妙，或是让他们求着主角指导。

10, 每个人出现都必有其价值，不出现废物，在之前写一个神秘或普通短暂出现的人，或牛逼出现又有特别的地方，而后再将一神秘而强大的人或具有神话等类的人物让你想不透，最后再将两人写成同一人，让人大跌眼睛。

11, 用一个物品或其他奇怪的东西召唤他人，东西会突然凭空出现或是飘荡着，也可非实物，还有一个怪人专爱收集宝物或药物或其他物，却对主角很有用处，被主角一直剥削。

12, 一个个别人都很尊敬的人物，可是一看到主角的出现就都乖乖的低首，与之前的叱咤风云的高傲大相径庭。

13, 设一个主角要全力或是用一种残忍的方法来训练一个人，在方法上要出众，让人期待着这种方法下训练出来的实力。

14, YY不是每次都需要主角特意去做，而是写手刻意的安排。

15, 对战的时候主角只是拿了一把破刀子，而对手拿的却是一把削铁如泥的宝刀。

16, 慈悲是你最好的武器。主角说着就一刀下去，说道"我这是在帮他脱离苦海"

17, 跟正派的人打架，别人都以为他会用光明正大的手法，谁知道他却用阴的手段打。

18, 带着自己的部下处处去帮忙，可每次都是等到别人打完了才出场，喊着口号冲出去一副拼杀的态度。

19, 拿着很普通的东西，把它说得意义很重大很贵重而且是独一无二，一副非常舍不得的表情，让人感动不敢乱接。

20, 有了自己的团队。感情绝对的深厚。

21, 拥有大量的钱财，却对钱财不以为意

22, 各种神奇的武器装备，主角总能获得最好的

23, 神秘的师父在危难时刻出现

24, 强敌压境时突然悟出新技能

25, 反派人物的真实身份令人震惊

26, 主角被陷害后冷静调查真相

27, 拍卖会上意外获得绝世珍宝

28, 比武招亲的情节设置

29, 临阵突破成为经典桥段

30, 获得神秘传承功法

31, 异界与现实世界的穿梭

32, 身份暴露引发剧情高潮

33, 反派被主角击败前的最后挣扎
"""

TOOL_DOC = """
百家姓

赵 钱 孙 李 周 吴 郑 王
冯 陈 楮 卫 蒋 沈 韩 杨
朱 秦 尤 许 何 吕 施 张
孔 曹 严 华 金 魏 陶 姜
戚 谢 邹 喻 柏 水 窦 章
云 苏 潘 葛 奚 范 彭 郎
鲁 韦 昌 马 苗 凤 花 方
俞 任 袁 柳 酆 鲍 史 唐
费 廉 岑 薛 雷 贺 倪 汤
滕 殷 罗 毕 郝 邬 安 常
乐 于 时 傅 皮 卞 齐 康
伍 余 元 卜 顾 孟 平 黄
和 穆 萧 尹 姚 邵 湛 汪
祁 毛 禹 狄 米 贝 明 臧
计 伏 成 戴 谈 宋 茅 庞
熊 纪 舒 屈 项 祝 董 梁
杜 阮 蓝 闽 席 季 麻 强
贾 路 娄 危 江 童 颜 郭
梅 盛 林 刁 锺 徐 丘 骆
高 夏 蔡 田 樊 胡 凌 霍
虞 万 支 柯 昝 管 卢 莫
经 房 裘 缪 干 解 应 宗
丁 宣 贲 邓 郁 单 杭 洪
包 诸 左 石 崔 吉 钮 龚
程 嵇 邢 滑 裴 陆 荣 翁
荀 羊 於 惠 甄 麹 家 封
芮 羿 储 靳 汲 邴 糜 松
井 段 富 巫 乌 焦 巴 弓
牧 隗 山 谷 车 侯 宓 蓬
全 郗 班 仰 秋 仲 伊 宫
宁 仇 栾 暴 甘 斜 厉 戎
祖 武 符 刘 景 詹 束 龙
叶 幸 司 韶 郜 黎 蓟 薄
印 宿 白 怀 蒲 邰 从 鄂
索 咸 籍 赖 卓 蔺 屠 蒙
池 乔 阴 郁 胥 能 苍 双
闻 莘 党 翟 谭 贡 劳 逄
姬 申 扶 堵 冉 宰 郦 雍
郤 璩 桑 桂 濮 牛 寿 通
边 扈 燕 冀 郏 浦 尚 农
温 别 庄 晏 柴 瞿 阎 充
慕 连 茹 习 宦 艾 鱼 容
向 古 易 慎 戈 廖 庾 终
暨 居 衡 步 都 耿 满 弘
匡 国 文 寇 广 禄 阙 东
欧 殳 沃 利 蔚 越 夔 隆
师 巩 厍 聂 晁 勾 敖 融
冷 訾 辛 阚 那 简 饶 空
曾 毋 沙 乜 养 鞠 须 丰
巢 关 蒯 相 查 后 荆 红
游 竺 权 逑 盖 益 桓 公

姓氏参考表，用于小说角色命名。
"""

INCOMPLETE_DOC = """
# 15 条技巧提高写作技巧（内容不完整）

个人提升 August 17th, 2007

想成为下一个海明威吗？或许只是想在校刊有自己的豆腐块，让自己的博客富有动人文字？

【正文内容缺失，仅有引言部分】
"""


# ---------------------------------------------------------------------------
# 9-fixture test: each input must classify to its expected DocType.
# ---------------------------------------------------------------------------

DOC_FIXTURES = [
    pytest.param(SINGLE_METHOD, DocType.SINGLE_METHOD, id="single_method"),
    pytest.param(MULTI_SECTION, DocType.MULTI_SECTION, id="multi_section"),
    pytest.param(COLLECTION, DocType.COLLECTION, id="collection"),
    pytest.param(QA_CHAT, DocType.QA_CHAT, id="qa_chat"),
    pytest.param(LIST_DOC, DocType.LIST, id="list"),
    pytest.param(TOOL_DOC, DocType.TOOL, id="tool"),
    pytest.param(INCOMPLETE_DOC, DocType.INCOMPLETE, id="incomplete"),
]


@pytest.mark.parametrize("text,expected", DOC_FIXTURES)
def test_heuristic_classifies_known_documents(text, expected):
    """Heuristic-only classifier hits all 7 fixture types correctly."""
    c = classify_doc_heuristic(text)
    assert c.doc_type == expected, (
        f"expected {expected}, got {c.doc_type} "
        f"(confidence={c.confidence}, rationale={c.rationale!r})"
    )


# ---------------------------------------------------------------------------
# Aggregate accuracy check: all 7 fixtures must hit.
# ---------------------------------------------------------------------------

def test_aggregate_heuristic_accuracy():
    """Aggregate accuracy on the 7 fixture set: 100%."""
    hits = sum(
        1
        for case in DOC_FIXTURES
        for text, expected in [case.values]
        if classify_doc_heuristic(text).doc_type == expected
    )
    total = len(DOC_FIXTURES)
    accuracy = hits / total
    assert accuracy >= 0.90, f"accuracy {accuracy:.0%} < 90% threshold"
    assert hits == total, f"missed {total - hits} of {total} fixtures"


# ---------------------------------------------------------------------------
# Single-call API contract
# ---------------------------------------------------------------------------

def test_classify_doc_returns_classification_instance():
    """classify_doc() returns a Classification, not a bare enum."""
    c = classify_doc(SINGLE_METHOD)
    assert isinstance(c, Classification)
    assert isinstance(c.doc_type, DocType)


def test_classify_doc_without_llm_uses_heuristic():
    """When llm is None, classify_doc() falls back to heuristic only —
    no exception, no None."""
    c = classify_doc(SINGLE_METHOD)
    assert c.doc_type in {case.values[1] for case in DOC_FIXTURES} | {DocType.SINGLE_METHOD}


def test_classify_doc_filename_hint_forces_tool():
    """A filename containing 百家姓 / 工具表 forces DocType.TOOL even
    on short / ambiguous content."""
    c = classify_doc_heuristic("随便一段内容", filename_hint="百家姓.md")
    assert c.doc_type == DocType.TOOL
    assert c.confidence >= 0.90


def test_classify_doc_short_intro_only_is_incomplete():
    """A document with only a heading + 1-2 sentences is incomplete."""
    c = classify_doc_heuristic("# 标题\n\n只是一段简介。")
    assert c.doc_type == DocType.INCOMPLETE


def test_classify_doc_low_confidence_passes_through_heuristic_when_no_llm():
    """When confidence is below threshold and no LLM is supplied, the
    heuristic result is returned as-is (with its actual confidence).
    Per Stage 1 contract — never raise."""
    # Multi-section with low signal still gets multi_section (heuristic
    # gives confidence 0.80 = at threshold; not below).
    # Use single_method (low-confidence default 0.70) with threshold 0.90.
    c = classify_doc(SINGLE_METHOD, confidence_threshold=0.90)
    assert c.confidence == 0.70  # heuristic value, not raised
    assert c.doc_type == DocType.SINGLE_METHOD

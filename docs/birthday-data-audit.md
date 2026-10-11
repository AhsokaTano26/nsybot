# 生日数据网络核查

核查日期：**2026-10-11**。核查对象为 [当前预设 CSV](../nsy/plugins/birthday/data/bangdream.csv)
中的 **61 条角色记录、57 位声优**，对应 [导入命令](birthday-import-commands.md) 中的 118 条生日数据。

本次使用多组中日文网络检索，逐项比较插件使用的公历生日月日 `MM-DD`。
优先采用官方角色介绍、本人官网、事务所、唱片公司和官方生日公告；
未取得可用一级资料的条目，采用专业声优杂志、动漫媒体等资料佐证。

## 结果与证据范围

**118 条生日月日均与本次核到的资料一致，未发现生日月日错误。**

| 范围 | 条数 | 月日不一致 | 主要证据 |
| --- | --- | --- | --- |
| 角色记录 | 61 | 0 | 60 条官方角色生日字段；米歇尔沿用奥泽美咲的生日资料 |
| 声优 | 57 | 0 | 50 位有官方来源；7 位主要依赖专业媒体佐证 |

这是一份截至核查日的来源比对结果。部分官方网站的搜索索引可以读取生日字段，
但直接打开页面返回 404、超时或无法提取正文；相关条目在表中标为“官方检索正文”，
不将搜索索引等同于成功读取当前网页。声优表中也标明了对应的读取方式。

米歇尔与奥泽美咲按用户明确要求**分开存储**，两条记录均使用 `10-01`，
不合并、不列为错误。日期依据来自
[奥泽美咲官方资料](https://bang-dream.bushimo.jp/character/hello-happy-world/okusawa-misaki/)：
该资料同时介绍了两者的关系，未取得米歇尔独立于美咲的官方生日字段。

## 出生年份的重点核查

生日提醒只使用月日，CSV 的“出生年份”不参与定时提醒。
本次没有对全部出生年份作完整审计；以下几项未取得官方年份依据，
**不能据此判定年份错误，也不能把它们标成已经官方确认**。

| 声优 | CSV 年份 | 核查说明 | 依据 |
| --- | --- | --- | --- |
| 志崎桦音 | 1995 | 本人官网及学校人物介绍未列出生年份；不能据大学经历推算成 1996 | [本人官网](https://kanonshizaki.com/profiles)、[学校人物介绍](https://www.senzoku.ac.jp/music/active_graduate/71535) |
| 米泽茜 | 1998 | 本次核到的生日资料只确认 12-31；出生年份未取得官方支持 | [本人简介](https://akaneyonezawa.com/profile)、[Animate Times](https://www.animatetimes.com/tag/details.php?id=25154) |
| 咲川雏乃 | 2004 | 事务所资料只列 01-22；2004 见于媒体资料，来源等级需区分 | [事务所资料](https://stay-luck.com/talent/sakikawa-hinano/)、[J:COM 资料](https://linkvod.myjcom.jp/artist/667714) |
| 花宫初奈 | 1999 | 事务所资料只列 10-24；本次未取得确认 1999 的官方依据 | [事务所资料](https://www.aoni.co.jp/search/hanamiya-niina.html) |

作为有完整官方日期的对照，橘芽衣的 `2008-11-19` 与
[Amuse 资料](https://www.amuse.co.jp/artist/A9019/)一致，凉泉樱花的 `2004-03-05` 与
[Sony Music Artists 资料](https://www.sma.co.jp/s/sma/artist/657)一致。

## 角色逐项核查（61 条）

中文名称沿用当前 CSV，日文名列出所引用官方资料的表记；RAISE A SUILEN
部分页面使用舞台名。这里核查的是生日日期，不将中日文译名差异判为生日错误。

| 当前名称 | 官方资料中的日文名 | 当前月日 | 核到月日 | 结论 | 来源 |
| --- | --- | --- | --- | --- | --- |
| 户山香澄 | 戸山香澄 | 07-14 | 07-14 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/poppinparty/toyama-kasumi/) |
| 花园多惠 | 花園たえ | 12-04 | 12-04 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/poppinparty/hanazono-tae/) |
| 牛込里美 | 牛込りみ | 03-23 | 03-23 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/poppinparty/ushigome-rimi/) |
| 山吹沙绫 | 山吹沙綾 | 05-19 | 05-19 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/poppinparty/yamabuki-saya/) |
| 市谷有咲 | 市ヶ谷有咲 | 10-27 | 10-27 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/poppinparty/ichigaya-arisa/) |
| 美竹兰 | 美竹蘭 | 04-10 | 04-10 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/afterglow/mitake-ran/) |
| 青叶摩卡 | 青葉モカ | 09-03 | 09-03 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/afterglow/aoba-moca/) |
| 上原绯玛丽 | 上原ひまり | 10-23 | 10-23 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/afterglow/uehara-himari/) |
| 宇田川巴 | 宇田川巴 | 04-15 | 04-15 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/afterglow/udagawa-tomoe/) |
| 羽泽鸫 | 羽沢つぐみ | 01-07 | 01-07 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/afterglow/hazawa-tsugumi/) |
| 丸山彩 | 丸山彩 | 12-27 | 12-27 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/pastel-palettes/maruyama-aya/) |
| 冰川日菜 | 氷川日菜 | 03-20 | 03-20 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/pastel-palettes/hikawa-hina/) |
| 白鹭千圣 | 白鷺千聖 | 04-06 | 04-06 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/pastel-palettes/shirasagi-chisato/) |
| 大和麻弥 | 大和麻弥 | 11-03 | 11-03 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/pastel-palettes/yamato-maya/) |
| 若宫伊芙 | 若宮イヴ | 06-27 | 06-27 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/pastel-palettes/wakamiya-eve/) |
| 凑友希那 | 湊友希那 | 10-26 | 10-26 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/roselia/minato-yukina/) |
| 冰川纱夜 | 氷川紗夜 | 03-20 | 03-20 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/roselia/hikawa-sayo/) |
| 今井莉莎 | 今井リサ | 08-25 | 08-25 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/roselia/imai-lisa/) |
| 宇田川亚子 | 宇田川あこ | 07-03 | 07-03 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/roselia/udagawa-ako/) |
| 白金燐子 | 白金燐子 | 10-17 | 10-17 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/roselia/shirokane-rinko/) |
| 弦卷心 | 弦巻こころ | 08-08 | 08-08 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/hello-happy-world/tsurumaki-kokoro/) |
| 濑田薰 | 瀬田薫 | 02-28 | 02-28 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/hello-happy-world/seta-kaoru/) |
| 北泽育美 | 北沢はぐみ | 07-30 | 07-30 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/hello-happy-world/kitazawa-hagumi/) |
| 松原花音 | 松原花音 | 05-11 | 05-11 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/hello-happy-world/matsubara-kanon/) |
| 奥泽美咲 | 奥沢美咲 | 10-01 | 10-01 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/hello-happy-world/okusawa-misaki/) |
| 米歇尔 | ミッシェル（奥沢美咲） | 10-01 | 10-01 | 一致（沿用美咲资料） | [官方身份与生日依据](https://bang-dream.bushimo.jp/character/hello-happy-world/okusawa-misaki/) |
| 仓田真白 | 倉田ましろ | 02-19 | 02-19 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/morfonica/kurata-mashiro/) |
| 桐谷透子 | 桐ヶ谷透子 | 12-16 | 12-16 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/morfonica/kirigaya-toko/) |
| 广町七深 | 広町七深 | 06-16 | 06-16 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/morfonica/hiromachi-nanami/) |
| 二叶筑紫 | 二葉つくし | 09-15 | 09-15 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/morfonica/futaba-tsukushi/) |
| 八潮瑠唯 | 八潮瑠唯 | 11-19 | 11-19 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/morfonica/yashio-rui/) |
| 和奏瑞依 | レイヤ | 01-13 | 01-13 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/raise-a-suilen/layer/) |
| 朝日六花 | ロック | 07-17 | 07-17 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/raise-a-suilen/lock/) |
| 佐藤益木 | マスキング | 05-12 | 05-12 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/raise-a-suilen/masking/) |
| 鳰原令王那 | パレオ | 03-25 | 03-25 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/raise-a-suilen/pareo/) |
| 珠手知由 | チュチュ | 12-07 | 12-07 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/raise-a-suilen/chu2/) |
| 高松灯 | 高松燈 | 11-22 | 11-22 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/mygo/takamatsu-tomori/) |
| 千早爱音 | 千早愛音 | 09-08 | 09-08 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/mygo/chihaya-anon/) |
| 要乐奈 | 要楽奈 | 02-22 | 02-22 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/mygo/kaname-rana/) |
| 长崎爽世 | 長崎そよ | 05-27 | 05-27 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/mygo/nagasaki-soyo/) |
| 椎名立希 | 椎名立希 | 08-09 | 08-09 | 一致 | [官方检索正文](https://bang-dream.bushimo.jp/character/mygo/shiina-taki/) |
| 三角初华 | 三角初華 | 06-26 | 06-26 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/avemujica/misumi-uika/) |
| 若叶睦 | 若葉睦 | 01-14 | 01-14 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/avemujica/wakaba-mutsumi/) |
| 八幡海铃 | 八幡海鈴 | 04-07 | 04-07 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/avemujica/yahata-umiri/) |
| 祐天寺若麦 | 祐天寺にゃむ | 06-01 | 06-01 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/avemujica/yutenji-nyamu/) |
| 丰川祥子 | 豊川祥子 | 02-14 | 02-14 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/avemujica/togawa-sakiko/) |
| 仲町阿拉蕾 | 仲町あられ | 08-16 | 08-16 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/yumemita/nakamachi-arale/) |
| 宫永野乃花 | 宮永ののか | 04-17 | 04-17 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/yumemita/miyanaga-nonoka/) |
| 峰月律 | 峰月律 | 02-07 | 02-07 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/yumemita/minetsuki-ritsu/) |
| 藤都子 | 藤都子 | 09-19 | 09-19 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/yumemita/fuji-miyako/) |
| 千石由乃 | 千石ユノ | 11-04 | 11-04 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/yumemita/sengoku-yuno/) |
| 汐见萤 | 汐見蛍 | 03-12 | 03-12 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/millsage/shiomi-hotaru/) |
| 伊泽枣 | 伊沢なつめ | 03-30 | 03-30 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/millsage/izawa-natsume/) |
| 琴平凪 | 琴平凪 | 12-10 | 12-10 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/millsage/kotohira-nagi/) |
| 滨崎茉幌 | 浜崎まほろ | 07-16 | 07-16 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/millsage/hamasaki-mahoro/) |
| 和泉朋花 | 和泉朋花 | 10-24 | 10-24 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/millsage/izumi-houka/) |
| 须贺蕾叶 | 須賀蕾叶 | 07-28 | 07-28 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/ikka-dumb-rock/suga-raika/) |
| 马桥心玖 | 馬橋心玖 | 10-04 | 10-04 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/ikka-dumb-rock/mahashi-miku/) |
| 矢仓蓬咲 | 矢倉蓬咲 | 05-06 | 05-06 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/ikka-dumb-rock/yakura-yomogi/) |
| 梅里千樱梨 | 梅里ちえり | 04-02 | 04-02 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/ikka-dumb-rock/umezato-chieri/) |
| 四宫宁月 | 四宮寧月 | 03-05 | 03-05 | 一致 | [官方检索正文](https://bang-dream-on.bushimo.jp/character/ikka-dumb-rock/shinomiya-shizuku/) |

## 声优逐项核查（57 位）

“专业媒体”表示本次没有取得足以单独确认日期的可用一级资料，不代表生日已发现错误。
这些条目为：三泽纱千香、远藤祐里香、mika、小原莉子、仓知玲凤、米泽茜、药师寺李有。
小原莉子还有本人生日直播的交叉佐证；米泽茜的生日也有官方公告的转引，
表中保守采用可核对的媒体人物资料作为主要依据。

| 当前名称 | 日文名／艺名 | 当前月日 | 核到月日 | 结论 | 来源 |
| --- | --- | --- | --- | --- | --- |
| 爱美 | 愛美 | 12-25 | 12-25 | 一致 | [官方资料](https://aimi.info/profile) |
| 大冢纱英 | 大塚紗英 | 10-10 | 10-10 | 一致 | [官方资料](https://www.saeotsuka.jp/profile/) |
| 西本里美 | 西本りみ | 10-25 | 10-25 | 一致 | [官方资料](https://hibikifan.com/nishimoto_rimi) |
| 大桥彩香 | 大橋彩香 | 09-13 | 09-13 | 一致 | [官方资料](https://ayaka-ohashi.com/profiles) |
| 伊藤彩沙 | 伊藤彩沙 | 08-17 | 08-17 | 一致 | [官方资料](https://hibikifan.com/ito_ayasa) |
| 佐仓绫音 | 佐倉綾音 | 01-29 | 01-29 | 一致 | [官方资料](https://www.aoni.co.jp/search/sakura-ayane.html) |
| 三泽纱千香 | 三澤紗千香 | 01-13 | 01-13 | 一致（媒体佐证） | [专业媒体](https://seigura.com/directory/1209/)、[交叉资料](https://www.animatetimes.com/tag/details.php?id=2008) |
| 加藤英美里 | 加藤英美里 | 11-26 | 11-26 | 一致 | [官方资料](https://www.stardust.co.jp/talent/voiceactor/katoemiri/) |
| 日笠阳子 | 日笠陽子 | 07-16 | 07-16 | 一致 | [官方资料](https://inari-inc.com/talent/yoko-hikasa/) |
| 金元寿子 | 金元寿子 | 12-16 | 12-16 | 一致 | [官方资料](https://pro-baobab.jp/actor/%E9%87%91%E5%85%83-%E5%AF%BF%E5%AD%90/) |
| 前岛亚美 | 前島亜美 | 11-22 | 11-22 | 一致 | [官方资料](https://maeshima-ami.net/profiles) |
| 小泽亚李 | 小澤亜李 | 08-10 | 08-10 | 一致 | [官方资料](https://nichinare.co.jp/parameter/actor_actress/detail/127/) |
| 上坂堇 | 上坂すみれ | 12-19 | 12-19 | 一致 | [官方资料](https://voicekit.jp/talent/uesakasumire/) |
| 中上育实 | 中上育実 | 06-18 | 06-18 | 一致 | [官方资料](https://aksent.co.jp/profile/nakagami_ikumi/) |
| 秦佐和子 | 秦佐和子 | 09-14 | 09-14 | 一致 | [官方资料](https://mausu.net/talent/hata-sawako.html) |
| 相羽爱奈 | 相羽あいな | 10-17 | 10-17 | 一致 | [官方资料](https://hibikifan.com/aiba_aina) |
| 工藤晴香 | 工藤晴香 | 03-16 | 03-16 | 一致 | [官方资料](https://kdharoom.com/profile/) |
| 远藤祐里香 | 遠藤ゆりか | 06-24 | 06-24 | 一致（媒体佐证） | [专业媒体](https://www.animatetimes.com/news/details.php?id=1385091564)、[交叉资料](https://www.animatetimes.com/tag/details.php?id=4120&p=1) |
| 中岛由贵 | 中島由貴 | 09-12 | 09-12 | 一致 | [官方资料](https://www.beffect.co.jp/talent/yuki/) |
| 樱川惠 | 櫻川めぐ | 10-24 | 10-24 | 一致 | [官方资料](https://sakuragawa-megu.com/profiles) |
| 明坂聪美 | 明坂聡美 | 01-02 | 01-02 | 一致 | [官方资料](https://amuleto.jp/talents/akesakasatomi.html) |
| 志崎桦音 | 志崎樺音 | 02-08 | 02-08 | 一致 | [官方检索正文](https://bushiroad-store.com/pages/february_birthday) |
| 伊藤美来 | 伊藤美来 | 10-12 | 10-12 | 一致 | [官方资料](https://columbia.jp/artist-info/itomiku/prof.html) |
| 田所梓 | 田所あずさ | 11-10 | 11-10 | 一致 | [官方资料](https://azusatadokoro.lantis.jp/profile/) |
| 吉田有里 | 吉田有里 | 08-18 | 08-18 | 一致 | [官方资料](https://sigma7.co.jp/actors/yoshida_yu-ri/) |
| 丰田萌绘 | 豊田萌絵 | 03-15 | 03-15 | 一致 | [官方资料](https://hibikifan.com/toyota_moe) |
| 黑泽朋世 | 黒沢ともよ | 04-10 | 04-10 | 一致 | [官方资料](https://www.toho-ent.co.jp/actor/42200) |
| 进藤天音 | 進藤あまね | 04-20 | 04-20 | 一致 | [官方资料](https://hibikifan.com/shindou_amane) |
| 直田姬奈 | 直田姫奈 | 04-17 | 04-17 | 一致 | [官方资料](https://columbia.jp/sugutahina/prof.html) |
| 西尾夕香 | 西尾夕香 | 03-31 | 03-31 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/nishio_yuka/) |
| mika | mika | 06-24 | 06-24 | 一致（媒体佐证） | [专业媒体](https://www.animatetimes.com/tag/details.php?id=9454)、[交叉资料](https://thetv.jp/person/2000055300/) |
| Ayasa | Ayasa | 10-19 | 10-19 | 一致 | [官方资料](https://ameblo.jp/ayasa-violin/entry-12211342300.html) |
| Raychell | Raychell | 01-13 | 01-13 | 一致 | [官方资料](https://avex.jp/raychell/profile/) |
| 小原莉子 | 小原莉子 | 02-03 | 02-03 | 一致（媒体佐证） | [专业媒体](https://www.animatetimes.com/news/details.php?id=1610420963)、[交叉资料](https://www.youtube.com/watch?v=eE08WviNja8) |
| 夏芽 | 夏芽 | 07-20 | 07-20 | 一致 | [官方检索正文](https://72beat.jp/) |
| 仓知玲凤 | 倉知玲鳳 | 05-22 | 05-22 | 一致（媒体佐证） | [专业媒体](https://seigura.com/directory/39962/)、[交叉资料](https://www.animatetimes.com/tag/details.php?id=9028) |
| 纺木吏佐 | 紡木吏佐 | 07-05 | 07-05 | 一致 | [官方资料](https://mittma.com/profile/risa_tsumugi/) |
| 羊宫妃那 | 羊宮妃那 | 03-26 | 03-26 | 一致 | [官方资料](https://www.aoni.co.jp/search/yomiya-hina.html) |
| 立石凛 | 立石凛 | 07-10 | 07-10 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/tateishi_rin/) |
| 青木阳菜 | 青木陽菜 | 01-05 | 01-05 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/aoki_hina/) |
| 小日向美香 | 小日向美香 | 03-14 | 03-14 | 一致 | [官方资料](https://www.s-inc.jp/mika-kohinata) |
| 林鼓子 | 林鼓子 | 05-15 | 05-15 | 一致 | [官方资料](https://ameblo.jp/rungirlsrun/entry-12297485190.html) |
| 佐佐木李子 | 佐々木李子 | 11-10 | 11-10 | 一致 | [官方资料](https://sasakirico.lantis.jp/profile/) |
| 渡濑结月 | 渡瀬結月 | 02-18 | 02-18 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/watase_yuzuki/) |
| 冈田梦以 | 岡田夢以 | 05-19 | 05-19 | 一致 | [官方资料](https://maysland.jp/) |
| 米泽茜 | 米澤茜 | 12-31 | 12-31 | 一致（媒体佐证） | [专业媒体](https://secure.eiga.com/person/372963/)、[交叉资料](https://www.animatetimes.com/tag/details.php?id=25154) |
| 高尾奏音 | 高尾奏音 | 09-10 | 09-10 | 一致 | [官方资料](https://ancheri.co.jp/talent/kanon_takao.html) |
| 药师寺李有 | 薬師寺李有 | 09-11 | 09-11 | 一致（媒体佐证） | [专业媒体](https://seigura.com/senior/173265/) |
| 千春 | 千春 | 04-10 | 04-10 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/chiharu/) |
| 结川麻希 | 結川あさき | 02-15 | 02-15 | 一致 | [官方资料](https://www.imenterprise.jp/profile.php?id=178) |
| 伊驹祐里惠 | 伊駒ゆりえ | 02-24 | 02-24 | 一致 | [官方资料](https://www.81produce.co.jp/actor_search/index.php/item?cell003=%E3%81%82%E8%A1%8C&cell004=&cell028=&cell029=%E5%A5%B3%E6%80%A7&id=395&keyword=&label=1&name=%E4%BC%8A%E9%A7%92%E3%80%80%E3%82%86%E3%82%8A%E3%81%88) |
| 咲川雏乃 | 咲川ひなの | 01-22 | 01-22 | 一致 | [官方资料](https://stay-luck.com/talent/sakikawa-hinano/) |
| 橘芽衣 | 橘めい | 11-19 | 11-19 | 一致 | [官方资料](https://www.amuse.co.jp/artist/A9019/) |
| 凉泉樱花 | 涼泉桜花 | 03-05 | 03-05 | 一致 | [官方资料](https://www.sma.co.jp/s/sma/artist/657) |
| 花宫初奈 | 花宮初奈 | 10-24 | 10-24 | 一致 | [官方资料](https://www.aoni.co.jp/search/hanamiya-niina.html) |
| 菱川花菜 | 菱川花菜 | 05-19 | 05-19 | 一致 | [官方资料](https://www.raccoon-dog.co.jp/talent/r20-hishikawa.html) |
| 远野光 | 遠野ひかる | 03-05 | 03-05 | 一致 | [官方检索正文](https://hibiki-cast.jp/hibiki_f/tono_hikaru/) |

## 对导入数据的处理

本次未发现需要更改的生日月日，因此保留预设 CSV 和六条批量导入命令中的日期。
米歇尔与奥泽美咲继续作为两条记录。出生年份的未确认项仅记在本报告中，
未把推测值写成确定的更正值。

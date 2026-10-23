# Attraction research and review policy

## Base catalog

The base catalog contains nine researched candidates for user review.
Candidate scope is Hainan's cycling corridor first, including worthwhile
inland detours with their route deviation recorded when reliable route data is
available.

## Additional candidate batch

Three candidates were added from two first-person Mafengwo trip reports:
Guangcun Silver Beach and Eman volcanic coast from a 2024 island-cycling
account, plus Dongjiao Coconut Grove from a 2024 Wenchang day-trip account.
These remain single-source leads, not consensus recommendations. The Eman
viewpoint's reported closure is time-sensitive. The coconut-grove area and
viewpoints still need precise coordinates; no approximate map pin is supplied.

## Wider island candidate batch

A second research batch adds 51 candidates from first-person Mafengwo and Ctrip
travel records, bringing the local catalog to 60 candidates. The material
includes island-cycling accounts, Wenchang city walks, and self-drive or family
itineraries. A route mention is not treated as a detailed review: every entry
remains unapproved, and single-source or itinerary-only records are marked as
limited evidence.

A third batch brought the catalog to 100 entries, including small coastal
landmarks, named viewpoints, village stops, and sub-locations inside larger
scenic areas. It uses six first-person Mafengwo trip reports from the same
travel writer, so these are not six independent sources per candidate and
should not be mistaken for broad consensus. The user-requested Shanqin Bay
Swallow Cave remains an unsourced lead with no experience summary or
coordinates pending source and safety verification.

A later research pass applied the parent-attraction deduplication rule:
the two Dongjiao Coconut Grove viewpoints, nine Tongguling internal points,
and the Stone Park "Haishi Rock" were merged into their parent attractions,
and the Yulinzhou Lighthouse was merged into the Yulinzhou protected-coast
candidate. New candidates and source observations were added from inspected
Mafengwo travelogues and Bilibili visitor videos, including small coastal
stops and Wuzhishan inland-city locations. At the end of this pass, the
combined catalog contained 106 candidates; 32 had coordinates
cross-referenced to OpenStreetMap.
The recent Bilibili entries are single-creator, title/location-level visit
leads, not detailed reviews or independent consensus. Other candidates remain
without map pins until a reliable location is confirmed.

A fifth research pass inspected additional Mafengwo first-person travelogues
and added three distinct candidates: Xinglong Bali Village, Qixianling Hot
Spring National Forest Park, and Lingshui Fuli Ocean World. The first two
reports are by the same travel writer as several earlier entries, so they are
not independent corroboration. The Ocean World report describes a visit during
typhoon-affected weather; closures and animal-interaction details are
time-sensitive. The combined catalog now contains 109 candidates, of which
32 have verified coordinates. These new entries have no map pins pending
reliable entrance coordinates.

The sixth research pass inspected a first-person Toutiao account of a Hainan
loop through Qionghai. It added Red Stone Beach, Tanmen Harbor, and the informal
Paigang Village seaside "door" photo stop. The same source notes that a
boardwalk was closed during the visit and identifies a cycling-supply-point
sign near the photo props; those are dated observations, not guarantees of
current access or service. The three candidates share one source and have no
verified coordinates. A separate Mafengwo family itinerary identified Lingshui's
Lingzai Bay as a tide-flat visit; its brief account notes rain and a late
arrival, so no broader wildlife or access claims are inferred. That adds a
second source platform, but the three Qionghai entries still share one author
and one source. A first-person Toutiao account from Chengmai added Fushan
Coffee Culture Town and Baoliang Ancient Village. Both are based on the same
single author's April 2025 visit; prices, the coffee museum renovation, and
village facilities are explicitly time-sensitive. A Sohu first-person account
and a separate Bilibili location-level Vlog identified Lingao Guyin Waterfall;
the waterfall entry uses the detailed Sohu visit account and treats the video
title only as independent location corroboration. Current trail access and
safety have not been verified. The catalog now contains 116 candidates, 32
with verified coordinates.

All attraction records are now consolidated in `data/attractions.json`, the
single source of truth loaded by the application. Retired numbered batch files
were moved to the Windows Recycle Bin after the merged catalog passed tests.
Add future candidates directly to the canonical file and update its count
assertions and this research summary.

## Catalog route order

The canonical JSON and the application API use the same regional order for a
counterclockwise loop starting in Haikou: Haikou, Chengmai, Lingao, Danzhou,
Baisha, Qiongzhong, Changjiang, Dongfang, Ledong, Wuzhishan, Baoting, Sanya,
Lingshui, Wanning, Qionghai, Tunchang, Ding'an, and Wenchang, then back to
Haikou. Inland counties appear as detours between adjacent coastal sections.
The browser renders attractions in API order. Within a region, the existing
record order is retained rather than implying an exact stop sequence where
reliable route evidence or verified locations are unavailable.

## Xiaohongshu manual note review

One Xiaohongshu note was opened at a time through the normal signed-in browser
interface; no crawler, bulk processing, or image download was used. The note
"骑行环海南都给我来燕子洞拍照🤳" by Haoola was opened and read. It describes
two ways to visit the existing Wanning Shanqin Bay Swallow Cave candidate:
push a bike down the slope and along roughly 500 metres of difficult sandy
beach, or leave the bike above and arrange a paid ride. The author replied in
the comments that they chose the ride up. This adds a single visitor-source
summary to the existing candidate, not a duplicate stop. Its reported route
conditions and 20–30 yuan fare are dated, unverified observations; no
coordinates, current transport service, or safety guarantee were inferred.

A separate note, "海南怎么不算中国骑行天花板｜5天东岸攻略", was also opened.
It mentions Sharmei Village and the Shanqin Bay coastal cycling road, but is
presented as a broad itinerary and does not establish a visit to the Swallow
Cave or provide independently verifiable stop-level observations. It was not
added as evidence to a specific attraction. No photos were downloaded or
cached.

A third note, "昌江小众打卡点｜霸王岭观景台" by 玖玖, explicitly labels the
location as Bawangling Viewpoint in Changjiang. Its caption contains no
firsthand description of the view; comments describe it as roadside and say
parking is limited, but these comments are unverified. A second note by
蓝调Time, "海南小众秘境✨霸王岭观景台，俯瞰小桂林山水", gives a text
navigation clue along Changjiang County Road 705 and claims nearby parking and
toilet facilities. These statements remain unverified. The two notes were
merged into the single location-level candidate 昌江霸王岭路边观景台; no
coordinates or claims about the view were added.

A separate Chengmai Leigong Island note had a generic, non-specific experience
narrative without verifiable firsthand details, so it was not used. Another
Qionghai "任意门" guide listed several amenities and photo stops but did not
establish the author's visit; it was not added to the existing Paigang Village
candidate. A note, "陵水免费景点龙头岭 真的出片", only names Longtoul Ridge
and does not establish a firsthand stop or precise access; comment text was not
reused as the author's experience. A separate "陵水尖岭｜0元小众秘境自驾导航
直接抄" post gives a Li'an Town lead but reads as a generalized guide without
clear firsthand testimony; it was not used to supplement or merge with the
Hongjiaoling viewpoint.

The note "海南这个超小众观景台，根本没法避雷❗️" by 李拜一 describes a
December 2025 visit to the Hongjiaoling coastal viewpoint in Lingshui. It
mentions views toward Xiangshui Bay, a narrow and steep approach, and
distinguishes the viewpoint from a nearby mountaintop observatory. This
single-source candidate has no coordinates; the note's driving directions do
not verify bicycle access or current opening status.

A note by 阿圆不打卡, "万宁🚴‍♀️骑行好风景都在村子里", describes a roughly
12 km ride from Shenzhou Peninsula to Chucun Houhai Beach, with little
elevation gain and few supply stops, ending at a sparsely visited wild beach.
The author says a nearby outdoor shop appears to rent surfboards. This is a
single dated ride report with no verified coordinates or current service
guarantees; 万宁赤村后海沙滩 was added as a separate candidate.

The note "雷公滩的红石头，比瀑布更值得看" by Moment gives a lead to the
upper Leigongtan river valley near Muses Lake in Fengmu Town, Tunchang, and
describes exposed riverbed, colored rock, and small water drops. It does not
explicitly say the author visited and attributes the location to recent posts.
屯昌雷公滩红石河谷 was added only as a clearly marked, unverified candidate
lead, without coordinates or verified experience claims.

A note by 匠拐拐, "陵水虎岭，我心目中的海岛天花板！免费版", describes the
author's self-drive visit to Huling and nearby Jianling in Lingshui. It mentions
the coconut grove parking area, beach and reef-protected shallows at Huling,
and sunset at Jianling; these are single-visit observations and do not verify
bicycle access, current road access, or safety conditions. Because the author
describes the two as distinct but only several hundred meters apart, they were
grouped into one candidate, 陵水虎岭与尖岭海岸, without coordinates.

The note "海南环岛Day2:屯昌到琼中" by 咪崽 records that the author went to
木色湖 after checking out and gives only a brief positive impression. It has no
specific shoreline or route detail, so 屯昌木色湖 was added as a limited
single-source candidate without coordinates or expanded experience claims.

The note "屯昌|美鹤园竹林|绿意满🍃" by 团团团团团子. describes the author's
short stay in the bamboo grove and the shade, coolness, and quiet there. Its
title and tags identify Meiheyuan in Tunchang, but the exact village location
and entrance remain unverified. 屯昌美鹤园竹林 was added as a single-source
candidate without coordinates or a bicycle-access claim. The catalog now
contains 123 candidates, 32 with verified coordinates; 77 more would be needed
to reach the requested target of 200.

## XHS route research: Haikou to Lingao

The note "海南环岛西进东出 D1🚴🚴海口-新盈镇" gives route distances and
recommendations but does not clearly establish the author's own ride or stops;
its mentions of Lingao Cape and Xinying Town were not used as firsthand
evidence. "海南环岛骑行solo｜Day 1️⃣" is a direct 118 km Haikou-to-Lingao
ride account, but gives no specific attraction or stop to add.

"🏝️海南岛民的环岛骑行1️⃣海口市区-临高角" by 小丸子的奇思妙想 is a
firsthand ride log naming Lingao Cape as its destination and overnight stop.
The author records 114 km and 434 m elevation but says a support vehicle took
them through the urban section, so this is not a full-distance cycling track.
The log mentions passing Bao'an Port and seeing returning fishing boats, and
Qiaotou Town as a possible rest point around 70 km; these are single-ride
observations. Its lodging and food recommendations were not treated as current
availability claims. The source was added to the existing 临高角风景区 record;
no duplicate candidate was created.

## Inland coverage follow-up: Qiongzhong and Baisha

A follow-up search checked Qiongzhong and Baisha, two counties with no
candidate records in the current catalog. Searches for Shihan Village (什寒村)
returned an inaccessible Toutiao article titled "琼中什寒村最出名的三个景点";
opening it redirected to the platform login page, so its contents were not
used. Bilibili search returned a route-preview video for the road between
Shireng Village and Shang'an Township, but it did not establish a distinct
visitor stop or an inspected attraction experience. A separate Bilibili search
for a Shihan Village vlog did not surface a relevant firsthand account.

For Baisha, the Bilibili video "一个人穷游中国-只拍县城-《白沙黎族自治县》"
(https://www.bilibili.com/zh-Hans/video/BV1XJADzpEdc/) was opened, but its
video was unavailable in the browser and its page exposed no specific
attraction observations. Qunar's Baisha traveler-story listing
(https://travelnews.qunar.com/ugc/city/baisha) linked accounts mentioning
Hongkan Waterfall, the meteorite crater, tea gardens, and other places. The
opened Hongkan itinerary
(https://travelnews.qunar.com/ugc/baisha-hongkan-waterfall-3day-family)
states that Qunar's content team edited the post and contains unusually
prescriptive details that could not be attributed confidently to the visitor's
original account. A Sohu article about Hongkan Waterfall
(https://www.sohu.com/a/926022838_121949166), published by "生活消费汇", gives
general location and scenery claims but no verifiable firsthand visit. The
related Toutiao article also redirected to login. These are leads for future
verification only; none met the firsthand-evidence threshold for a catalog
change. No candidate or source was added, and the catalog remains at 116
candidates with 32 verified coordinates.

The Qunar traveler-story listing for Tunchang
(https://travelnews.qunar.com/ugc/city/tunchang) was also reviewed. Its six
summaries mix a hotel account, editorially attributed entries, and itinerary
roundups; no linked original visitor account was inspected in this pass. The
listing surfaced Dream Fragrance Valley (梦幻香山), Muse Lake (木色湖), and
Yangjiaoling Crystal Mine (羊角岭水晶矿) as leads, but no new candidate or
experience source was added from listing summaries alone.

Ctrip travelogue pages are retained as provenance links only; the experience
summaries and available coordinates are stored locally. The links are not
required for offline display.

## Coastal cross-validation follow-up: 2026-10-23

The current focus is coastal stops and beaches near the cycling route, with
cross-platform checks of existing candidates before adding more broad-area
records. The opened Mafengwo travelogue "我在马蜂窝写游记第三期｜乐东·东方2日行：
尖峰岭雨林・莺歌海盐田・四更乳猪：海南西线三重奏" mentions Longmu Bay as a
coastal route stop but does not identify a particular beach entrance or give
detailed on-site observations. This matches the existing 乐东龙沐湾 candidate,
whose record already cites that travelogue.

A normal Xiaohongshu search for 龙沐湾 beach and sunset returned only the page
shell and platform "薯队长遇到了点小麻烦" errors; no result note could be
opened or inspected. Therefore no Xiaohongshu URL was added and the candidate
is not considered cross-validated by this attempt. For successful checks,
store the opened note's canonical URL and source metadata under the attraction's
`sources` array (`sources[].url`), not in an extra unsupported metadata field.

## Coastal note review: 100-note request, progress 13/100

The first opened note, "🚴海口骑行！“西海岸”的绝美落日☄🏝", describes a
ride from Haikou Bay toward Xinhai Port, with a stop at Holiday Beach and an
unnamed shore near the port. The author describes crowding and buying coconut
water at Holiday Beach, but gives no year-specific visit date. The unnamed
shore could not be placed reliably and was not added or merged with Cloud
Camping Beach.

The second note, "海口骑车真的会上瘾🌊" by molly W, lists Holiday Beach and
its observation pavilion as stops on a Haikou coastal ride and mentions sunset.
Its route and supply statements are generic and not independently verified.
Together, the two opened notes support a new, limited Holiday Beach candidate;
their original Xiaohongshu URLs are recorded in that record's `sources`
metadata. This is same-platform corroboration only, not cross-platform
validation.

The third opened note, "海南东线骑行路线｜5天496km怎么骑", lists east-coast
route stops but does not clearly establish a firsthand ride or actual stops.
It was retained only as a lead; no source was added to existing attractions.

The fourth note, "环海南岛Day4 - 风车海岸" by 斌go, is a day-labeled island
cycling log. The author names 古海忆韵观景台, 鱼鳞洲自然风景保护区, and 感恩角
观景台 as windmill photo stops and mentions walking through trees to an
unnamed beach for sunset. It does not identify that beach. The Xiaohongshu URL
was added to the existing 东方风车海岸 record and, for the explicit stop
mention only, to 东方鱼鳞洲自然风景保护区; no unnamed beach or duplicate
viewpoint was created. This is visitor-source cross-checking, not independent
verification of access or current conditions.

The fifth opened note, "环海南岛骑行Day1 海口-海花岛" by 南山伐木累, is a
first-person Haikou-to-Haihua Island ride log. The author describes hazardous
mixed surfaces and junctions on Haikou's route to Xinhai Port, says supplies
were sparse on the route, mentions eating and refilling water near Lingao Cape,
and reports passing Guangcun Silver Beach and Longmen Jilang without a long
stop because it was not high tide and the scenery seemed unremarkable. Its
Xiaohongshu URL was added to those three existing attraction records with
claims limited to the note's actual route observations. The note also names
Yubao Canglang Viewing Platform, but its exact location and parent attraction
were not established, so no candidate was added. The catalog remains at 124
candidates with 32 verified coordinates.

The sixth opened note, "醉美环海🚴‍♂️ | 文昌➠万宁山钦湾路段" by Miss Choi |
此时彼地, is dated 02-08 without a visible year. Its text names Zhengmenling
Bridge and says the north end leads down to Shanqin Bay Swallow Cave, describing
the beach rocks positively. However, the note does not clearly state that the
author personally rode to or stopped at the location. It is therefore logged
as a location lead but not added as visitor-experience evidence; no year or
visit is inferred from the date or comments.

The seventh note, "海南岛骑行：儋州海花岛-东方" by 六亲不认的调色, is dated
2025-12-30 and gives first-person details for the west-coast ride. The author
describes the 昌江7号彩虹公路驿站 as a strong resupply stop with a toilet,
coconuts, and a beach, while warning of a longer sparse stretch afterward.
They separately praise the 棋子湾玻璃海公路 and describe the coastal road
descending toward the sea. These are two distinct route-planning stops in the
note, not duplicate records for 棋子湾大小角公园. Both were added as
single-source candidates without map coordinates; facility status, route
measurements, access, and exact map entrances remain unverified. The catalog
now contains 126 candidates with 32 verified coordinates. Seven note bodies
have been inspected out of the requested 100; search cards and itinerary
snippets are not counted.

The eighth note, "海南🚴🏻‍♀️含海量极高的一天太喜欢沙滩了", gives a short
first-person ride from Xinying Town to Haihua Island and reports 95.88 km plus
heavy water and drink consumption. Its body does not name a beach stop or
provide a location-specific observation, so no existing attraction was
updated and no source was added. The displayed date is 04-02 without a year,
and the author name was not recorded in the inspected note view.

The ninth note, "三亚新修的骑行绿道 海棠河公园" by 一而再、再而三, reports a
new greenway with an approximate 10 km one-way/20 km round-trip length and
little traffic. The text directs readers to navigate to Haitang River Park,
but the exact start/end points and connection to the island loop are not
provided. This distinct Sanya cycling detour was added as a single-source
candidate without coordinates; the date is displayed only as 01-07, with no
year. The catalog now contains 127 candidates with 32 verified coordinates.
Nine note bodies have been inspected out of the requested 100; search cards
and itinerary snippets are not counted.

The tenth note, "环海南岛骑行 day3儋州-海花岛-海头镇", is a first-person
ride account dated in its text to 2025-12-16. The author describes visiting
Haihua Island's commercial area and rates the island scenery positively, then
continuing to Haitou Town for the night and criticizing that night's lodging.
The Xiaohongshu URL was added to the existing Haihua Island record only; the
dated lodging assessment is not treated as a current hotel recommendation or
as evidence for an attraction in Haitou. The note reports that day's mileage
and elevation, which remain unverified. Ten note bodies have been inspected
out of the requested 100; search cards and itinerary snippets are not counted.

The eleventh note, "海南环岛骑行一定要途径莺歌海！！！" by 吴名之辈🐯,
describes a rider's route choice around Yinggehai and warns of a poor road
section on an alternative route. It recommends the Hainan Coastal Tourism
Highway rather than a shortcut via a national road; this is one rider's
route-specific observation, not current road-condition verification. Its
canonical note URL was added to the existing 乐东莺歌海 candidate; no new
attraction was created. The visible publication date shows only 01-26, so no
year was inferred.

The twelfth note, "海南环岛骑行DAY3️⃣" by Darren, is a first-person
儋州-to-东方 ride log dated 2025-05-09. The author reports passing and
stopping at 沙渔塘村, describing fishing boats, a beach, wooden houses, and a
coastal road photo stop. This is useful firsthand evidence, but the note alone
does not establish the village's precise map location or region in the
catalog's geography. It remains an unmerged lead; no attraction or source was
added until the location can be matched reliably. Twelve note bodies have
been inspected out of the requested 100; search cards and itinerary snippets
are not counted.

The thirteenth note, "海南西线环岛4日day1之临高儋州（附路线图）" by 小森林
（有猫版）, is a first-person self-drive account; its displayed publication
date is 10-04 without a year. It describes 临高角海水 and a then-closed
boardwalk, 东英国际慢城赶海公园 and the “幸福号船” photo stop, as well as
visits to 光村银滩, 龙门激浪, and 儋州龙腾云霞观景台. The note's URL was
added to those existing records and to a new, limited 东英 candidate. The
author's experiences at 光村银滩, 龙门激浪, and 龙腾云霞 are specifically
attributed and date/access conditions are not generalized. Although the note
is a self-drive trip rather than a cycling log, several stops are relevant to
the coastal route; vehicle access is not treated as proof of bicycle access.
The catalog now contains 128 candidates with 32 verified coordinates.
Thirteen note bodies have been inspected out of the requested 100; search
cards and itinerary snippets are not counted.

## Offline requirement

The approved catalog must remain usable without an internet connection. Save
the reviewed attraction description, coordinates, categories, experience
summary, and rights-cleared representative images in the local catalog/export.
Source links are optional provenance for later manual review; they must not be
required to render the attraction details or photos.

Do not use a search API as a substitute for locally stored, reviewed content.
When a platform's API restricts caching, redistribution, aggregation, or
offline use, keep that API data out of the offline catalog. A URL recorded as
a source does not itself grant rights to copy the linked text or images.

## Evidence

- Prefer first-person visitor accounts from the last three years.
- Aim for at least three independent visitor sources per attraction. Fewer
  sources are acceptable only when the record is explicitly marked as limited.
- Do not use official tourism promotional copy as the visitor-experience
  summary. Neutral sources may be used to cross-check objective facts such as
  location and operating details.
- Keep the original URL, platform, title, author when available, publication
  date when available, and retrieval date.
- Summarize experience in original wording. Do not reproduce long passages.
- Keep positive and negative observations separately attributed; do not
  manufacture a cross-platform numerical rating.
- Mark uncertain coordinates, stale operating details, and unsupported claims.

## Images

- Show a source link or platform-provided embed where permitted.
- Do not download or redistribute an image without explicit reuse permission.
- Local image files are allowed only when reuse is authorized or the user
  uploaded the image. Store the rights state and source alongside each image.
- If image rights are unclear, keep the reference URL and do not cache the file.
- A link-only image is not an offline image and must not be presented as
  available offline.

## User review

Each candidate is reviewed individually and can be edited, approved, or
rejected. Candidate status, source count, date freshness, and location
confidence should be visible during review. An unverified candidate must not
appear as a verified visitor recommendation.

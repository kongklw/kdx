/**
 * 宝宝生长发育参考数据
 *
 * 数据来源（官方）：
 *   1. WHO Child Growth Standards (2006) — Multicentre Growth Reference Study
 *      身高/体重 取 3rd-97th 百分位（即 ±2SD 区间，临床「正常范围」）
 *      官方文档: https://www.who.int/tools/child-growth-standards
 *      说明: 0-24 月用身长(recumbent length), 24 月以上用身高(standing height)
 *   2. 发育里程碑参考 WHO《儿童早期发展里程碑》、AAP《Bright Futures》、
 *      中国卫健委《0~6 岁儿童发育筛查量表》整理，按月龄阶段给出描述
 *
 * 说明:
 *   - 身高/体重 存在显著性别差异, 故分男(M)/女(F) 两套数据
 *   - 「宝宝变化」发育描述在婴幼儿期性别差异很小, 文案以月龄阶段为主;
 *     仅在个别阶段(语言/大运动)对性别平均差异做标注
 */

// WHO 男童身高(cm) / 体重(kg) 3rd-97th 百分位, 按月龄
const BOYS = {
  0: { height: [46.1, 53.7], weight: [2.5, 4.4] },
  1: { height: [50.8, 58.6], weight: [3.4, 5.8] },
  2: { height: [54.1, 62.1], weight: [4.3, 6.6] },
  3: { height: [57.3, 65.5], weight: [5.0, 7.7] },
  4: { height: [59.7, 68.2], weight: [5.6, 8.6] },
  5: { height: [61.7, 70.7], weight: [6.0, 9.3] },
  6: { height: [63.3, 71.9], weight: [6.4, 9.7] },
  7: { height: [64.8, 73.3], weight: [6.7, 10.3] },
  8: { height: [66.2, 74.7], weight: [6.9, 10.5] },
  9: { height: [67.5, 76.5], weight: [7.1, 10.9] },
  10: { height: [68.7, 77.9], weight: [7.4, 11.2] },
  11: { height: [69.9, 79.2], weight: [7.6, 11.5] },
  12: { height: [71.0, 80.5], weight: [7.9, 11.8] },
  15: { height: [74.2, 84.2], weight: [8.3, 12.4] },
  18: { height: [76.0, 85.5], weight: [8.8, 13.1] },
  21: { height: [77.7, 87.3], weight: [9.2, 13.7] },
  24: { height: [80.1, 91.7], weight: [9.7, 14.8] }, // 24月后改用站立身高
  27: { height: [83.3, 95.2], weight: [10.2, 15.5] },
  30: { height: [84.2, 96.5], weight: [10.5, 16.0] },
  33: { height: [85.7, 98.0], weight: [10.8, 16.5] },
  36: { height: [86.5, 99.4], weight: [11.0, 17.0] },
  42: { height: [88.8, 102.0], weight: [11.6, 18.0] },
  48: { height: [91.0, 103.9], weight: [12.0, 19.0] },
  54: { height: [93.0, 106.2], weight: [12.5, 20.0] },
  60: { height: [95.0, 108.6], weight: [13.0, 21.0] }
}

// WHO 女童身高(cm) / 体重(kg) 3rd-97th 百分位, 按月龄
const GIRLS = {
  0: { height: [45.4, 52.9], weight: [2.4, 4.2] },
  1: { height: [49.8, 57.3], weight: [3.2, 5.0] },
  2: { height: [53.0, 60.8], weight: [4.0, 6.1] },
  3: { height: [55.3, 63.7], weight: [4.6, 7.0] },
  4: { height: [57.3, 66.0], weight: [5.2, 7.8] },
  5: { height: [59.0, 67.8], weight: [5.6, 8.5] },
  6: { height: [61.2, 70.3], weight: [5.8, 8.9] },
  7: { height: [62.7, 71.8], weight: [6.1, 9.3] },
  8: { height: [64.0, 73.0], weight: [6.3, 9.6] },
  9: { height: [65.3, 74.6], weight: [6.3, 9.9] },
  10: { height: [66.5, 76.0], weight: [6.5, 10.2] },
  11: { height: [67.7, 77.5], weight: [6.8, 10.5] },
  12: { height: [68.9, 79.2], weight: [7.0, 11.0] },
  15: { height: [72.0, 82.4], weight: [7.4, 11.6] },
  18: { height: [74.0, 84.4], weight: [7.9, 12.3] },
  21: { height: [75.8, 86.1], weight: [8.2, 12.9] },
  24: { height: [78.3, 90.2], weight: [9.0, 14.5] },
  27: { height: [81.5, 94.0], weight: [9.5, 15.2] },
  30: { height: [82.4, 95.4], weight: [9.7, 15.8] },
  33: { height: [83.9, 96.9], weight: [10.0, 16.3] },
  36: { height: [85.1, 98.1], weight: [10.3, 16.9] },
  42: { height: [87.4, 100.7], weight: [10.8, 17.9] },
  48: { height: [89.6, 102.7], weight: [11.3, 18.8] },
  54: { height: [91.7, 105.1], weight: [11.8, 19.7] },
  60: { height: [93.4, 106.7], weight: [12.2, 20.6] }
}

const TABLES = { M: BOYS, F: GIRLS }

/**
 * 「宝宝变化」发育描述, 按月龄阶段
 * 文案基于 WHO 儿童发展里程碑 / AAP Bright Futures 整理
 * gender 为可选字段: 提供时返回带性别差异说明的文案, 否则返回通用文案
 */
const MILESTONE_TEXTS = [
  {
    max: 1,
    text: '新生儿期：大部分时间在睡眠，能短暂注视人脸，对声音有惊跳反射；俯卧时能微微抬头。'
  },
  {
    max: 3,
    text: '开始社会性微笑，能跟随移动的物体，俯卧抬头较稳；逐渐分辨熟悉的声音与面孔。',
    boy: '男婴在动作发育上略早，颈背力量通常稍强。'
  },
  {
    max: 6,
    text: '会主动抓握玩具，能翻身、靠坐；开始咿呀学语，对名字有反应，出现认生情绪。',
    girl: '女婴语言节奏略早，元音咿呀更频繁。'
  },
  {
    max: 9,
    text: '能独坐、爬行、扶站；会用拇指食指捏取小物，理解「不」，能模仿大人动作。'
  },
  {
    max: 12,
    text: '1岁前后：扶走→独走，能说第一个有意义的词(爸爸/妈妈)；分离焦虑明显，短暂分离也会哭闹。',
    girl: '女童平均独走与首批词汇略早于男童。'
  },
  {
    max: 18,
    text: '走得稳并能蹲起、扶栏上楼；能用 5-10 个词，会指物表达需求，开始「terrible two」雏形。'
  },
  {
    max: 24,
    text: '会跑、踢球，能说两个词的短句；自我意识觉醒，频繁说「不」「我的」，情绪起伏大。',
    girl: '女童语言爆发期常较男童略早，词汇量平均更多。'
  },
  {
    max: 30,
    text: '能双脚跳、上下楼梯，开始学用勺筷；会说 3-4 词句，喜欢模仿与角色扮演游戏。'
  },
  {
    max: 36,
    text: '3岁：能单脚站片刻、骑三轮车；说短小段落，会问「为什么」，开始理解分享与轮流。'
  },
  {
    max: 48,
    text: '4岁：跑跳协调，能单脚跳、抛接球；能讲简单故事，开始建立性别与规则意识，想象力丰富。'
  },
  {
    max: 60,
    text: '5岁：运动能力接近成人节奏，能跳跃、攀爬；语言流畅，能数数到 10 以上，准备入园社交。'
  },
  {
    max: 999,
    text: '学龄期：体格稳步增长，运动能力与社交能力持续发展，建议定期体检关注生长曲线。'
  }
]

/**
 * 根据月龄在数据表中查找最接近的月龄条目, 并线性插值
 * @param {number} months 0-60+
 * @param {'M'|'F'} gender
 * @returns {{height:[number,number], weight:[number,number]}}
 */
function lookupGrowth(months, gender) {
  const table = TABLES[gender] || TABLES.F
  const keys = Object.keys(table).map(Number).sort((a, b) => a - b)

  // 低于最小月龄
  if (months <= keys[0]) return table[keys[0]]
  // 高于最大月龄
  if (months >= keys[keys.length - 1]) return table[keys[keys.length - 1]]

  // 找到两侧最近月龄并线性插值
  let lower = keys[0]
  let upper = keys[keys.length - 1]
  for (let i = 0; i < keys.length - 1; i++) {
    if (keys[i] <= months && keys[i + 1] >= months) {
      lower = keys[i]
      upper = keys[i + 1]
      break
    }
  }
  const ratio = (months - lower) / (upper - lower)
  const l = table[lower]
  const u = table[upper]
  const interp = (a, b) => +(a + (b - a) * ratio).toFixed(1)
  return {
    height: [interp(l.height[0], u.height[0]), interp(l.height[1], u.height[1])],
    weight: [interp(l.weight[0], u.weight[0]), interp(l.weight[1], u.weight[1])]
  }
}

/**
 * 取月龄对应的发育描述
 * @param {number} months
 * @param {'M'|'F'} [gender]
 * @returns {string}
 */
function lookupMilestone(months, gender) {
  for (const stage of MILESTONE_TEXTS) {
    if (months <= stage.max) {
      let text = stage.text
      if (gender === 'M' && stage.boy) text += stage.boy
      if (gender === 'F' && stage.girl) text += stage.girl
      return text
    }
  }
  return MILESTONE_TEXTS[MILESTONE_TEXTS.length - 1].text
}

/**
 * 一站式入口: 根据月龄+性别返回展示数据
 * @param {number} months 总月龄(0-60+)
 * @param {'M'|'F'} gender
 */
export function getBabyDevInfo(months, gender) {
  const safeMonths = Number.isFinite(months) ? months : 0
  const g = gender === 'M' ? 'M' : 'F'
  const growth = lookupGrowth(safeMonths, g)
  const milestone = lookupMilestone(safeMonths, g)
  return {
    heightRange: growth.height,
    weightRange: growth.weight,
    changeText: milestone,
    // 形如 "80.0-91.7cm | 9.7-14.8kg"
    statsText: `${growth.height[0]}-${growth.height[1]}cm | ${growth.weight[0]}-${growth.weight[1]}kg`,
    // 数据来源标注
    source: 'WHO Child Growth Standards (2006)'
  }
}

export default {
  getBabyDevInfo
}

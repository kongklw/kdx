<template>
  <van-popup
    :value="visible"
    position="bottom"
    :style="{ height: '92%' }"
    round
    @input="onPopupInput"
  >
    <div class="bazi-page">
      <van-nav-bar :title="title" left-text="关闭" @click-left="close" />

      <div class="bazi-body">
        <div v-if="loading" class="loading-wrap">
          <van-loading size="24" vertical>正在测算八字...</van-loading>
        </div>

        <template v-else-if="data">
          <!-- 基础信息 -->
          <div class="info-card">
            <div class="info-name">
              {{ data.name }}
              <span class="zodiac-tag">属{{ data.zodiac }}</span>
              <span class="zodiac-tag element-tag" :style="eleStyle(data.life_element)">{{ data.life_element }}命</span>
            </div>
            <div class="info-line">公历 {{ data.solar_date }} · 农历 {{ data.lunar_text }}</div>
            <div class="info-line muted">年柱纳音「{{ data.year_nayin }}」· 年干支 {{ data.year_ganzhi }}</div>
          </div>

          <!-- 四柱 -->
          <div class="section-title">八字四柱</div>
          <div class="pillars">
            <div
              v-for="p in data.pillars"
              :key="p.key"
              class="pillar"
              :class="{ 'pillar-empty': !p.ganzhi }"
              @click="!p.ganzhi && openHourPicker()"
            >
              <div class="pillar-label">{{ p.label }}</div>
              <template v-if="p.ganzhi">
                <div class="pillar-char" :style="eleStyle(p.gan_wuxing)">
                  {{ p.gan }}<i>{{ p.gan_yinyang }}{{ p.gan_wuxing }}·{{ p.gan_shishen }}</i>
                </div>
                <div class="pillar-char" :style="eleStyle(p.zhi_wuxing)">
                  {{ p.zhi }}<i>{{ p.zhi_yinyang }}{{ p.zhi_wuxing }}</i>
                </div>
                <div class="pillar-nayin">{{ p.nayin }}·{{ p.dishi }}</div>
                <div class="pillar-hide">藏{{ p.zhi_hide_gan }}</div>
              </template>
              <template v-else>
                <div class="pillar-tips">未选时辰<br>点击补录</div>
              </template>
            </div>
          </div>

          <!-- 时辰补录 -->
          <div class="hour-bar">
            <span class="hour-label">出生时辰</span>
            <span v-if="hourText" class="hour-value">{{ hourText }}</span>
            <span v-else class="hour-value muted">未选择（按三柱统计）</span>
            <span class="hour-action" @click="openHourPicker">{{ data.hour === null ? '选择' : '修改' }}</span>
            <span v-if="data.hour !== null" class="hour-action clear" @click="clearHour">清除</span>
          </div>

          <!-- 换日流派 -->
          <div class="sect-row">
            <span class="sect-label">换日流派</span>
            <span class="sect-chip" :class="{ active: data.sect === 2 }" @click="setSect(2)">00:00 换日</span>
            <span class="sect-chip" :class="{ active: data.sect === 1 }" @click="setSect(1)">23:00 换日</span>
            <span class="sect-note">仅影响 23:00-24:00 出生者的日柱，其余时间两派结果一致。</span>
          </div>

          <!-- 五行统计 -->
          <div class="section-title">
            五行统计
            <span class="section-sub">（{{ data.count_basis === 8 ? '含时柱八字' : '暂按时柱缺失三柱统计' }}）</span>
          </div>
          <div class="wx-card">
            <div v-for="w in wuxingList" :key="w.name" class="wx-row">
              <span class="wx-name" :style="{ color: w.color }">{{ w.name }}</span>
              <div class="wx-track">
                <div class="wx-bar" :style="{ width: w.pct + '%', background: w.color }" />
              </div>
              <span class="wx-count">{{ w.count }}</span>
            </div>
            <div class="wx-summary">
              <span class="wx-chip" :style="eleStyle(data.rizhu.wuxing)">日主 {{ data.rizhu.gan }}（{{ data.rizhu.yinyang }}{{ data.rizhu.wuxing }}）</span>
              <span v-if="data.geju" class="wx-chip chip-geju">{{ data.geju }}</span>
              <span v-if="data.strongest_wuxing" class="wx-chip" :style="eleStyle(data.strongest_wuxing)">{{ data.strongest_wuxing }}偏旺</span>
              <span v-if="data.missing_wuxing.length" class="wx-chip chip-warn">缺 {{ data.missing_wuxing.join('、') }}</span>
              <span v-else class="wx-chip chip-ok">五行俱全</span>
            </div>
          </div>

          <!-- 命理细节 -->
          <div class="know-card detail-card">
            <div class="know-head">命理细节</div>
            <div class="detail-row">
              <span class="detail-label">格局</span>
              <span class="detail-value">{{ data.geju }}<i class="detail-sub">月令本气十神：{{ data.geju_shishen }}</i></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">命宫</span>
              <span class="detail-value">{{ data.minggong }}<i class="detail-sub">主先天禀赋与心性归宿</i></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">胎元</span>
              <span class="detail-value">{{ data.taiyuan }}<i class="detail-sub">受胎之月干支，主先天根基</i></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">身宫</span>
              <span class="detail-value">{{ data.shengong }}<i class="detail-sub">主后天发展与身体</i></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">旬空</span>
              <span class="detail-value">{{ data.xunkong }}<i class="detail-sub">日柱旬空，落空之字力量减弱</i></span>
            </div>
          </div>

          <!-- 大运流年 -->
          <div class="know-card">
            <div class="know-head">大运流年</div>
            <template v-if="data.yun">
              <div class="yun-start">
                {{ data.yun.gender === 1 ? '男命' : '女命' }} · 出生后 {{ data.yun.start_text }} 起运<template v-if="data.yun.start_solar">（{{ data.yun.start_solar }}）</template>
                <span v-if="data.hour === null" class="yun-warn">未选时辰，起运按 0 点估算</span>
              </div>
              <div class="dayun-scroll">
                <div
                  v-for="(d, i) in data.yun.dayuns"
                  :key="i"
                  class="dayun-chip"
                  :class="{ active: i === activeDayun }"
                  @click="activeDayun = i"
                >
                  <b>{{ d.ganzhi || '起运前' }}</b>
                  <span>{{ d.start_year }}-{{ d.end_year }}</span>
                  <span>{{ d.start_age }}-{{ d.end_age }}岁</span>
                </div>
              </div>
              <div class="liunian-grid">
                <div
                  v-for="ln in data.yun.dayuns[activeDayun].liunian"
                  :key="ln.year"
                  class="liunian-item"
                  :class="{ now: ln.year === currentYear }"
                >
                  <b>{{ ln.ganzhi }}</b>
                  <span>{{ ln.year }}</span>
                  <span>{{ ln.age }}岁</span>
                </div>
              </div>
              <div class="cycle-note">十年一步大运，点击大运可查看该步十年内的流年干支；当前年份高亮显示。</div>
            </template>
            <template v-else>
              <div class="yun-tip">排大运需要性别（阳男阴女顺排、阴男阳女逆排），请补录：</div>
              <div class="gender-btns">
                <span class="gender-btn" @click="setGender(1)">男</span>
                <span class="gender-btn" @click="setGender(0)">女</span>
              </div>
            </template>
          </div>

          <!-- 五行八卦知识 -->
          <div class="section-title">五行八卦知识</div>

          <div class="know-card">
            <div class="know-head">五行释义</div>
            <div class="ele-grid">
              <div v-for="e in elementKnowledge" :key="e.name" class="ele-item">
                <div class="ele-head" :style="{ color: e.color }">
                  {{ e.name }}<span class="ele-trigram">{{ e.trigrams }}</span>
                </div>
                <div class="ele-meta">{{ e.direction }} · {{ e.season }} · 尚{{ e.colorName }}</div>
                <div class="ele-desc">{{ e.desc }}</div>
                <div class="ele-organ">脏腑：{{ e.organ }}</div>
              </div>
            </div>
          </div>

          <div class="know-card">
            <div class="know-head">天干地支阴阳</div>
            <div class="gz-grid">
              <div v-for="g in ganTable" :key="g.char" class="gz-item" :style="eleStyle(g.ele)">
                <b>{{ g.char }}</b><span>{{ g.yy }}{{ g.ele }}</span>
              </div>
            </div>
            <div class="gz-grid zhi">
              <div v-for="g in zhiTable" :key="g.char" class="gz-item" :style="eleStyle(g.ele)">
                <b>{{ g.char }}</b><span>{{ g.yy }}{{ g.ele }}</span>
              </div>
            </div>
            <div class="cycle-note">天干地支皆分阴阳。年命纳音（如「{{ data.year_nayin }}」为{{ data.life_element }}命）本身不再分阴阳，其阴阳以生年天干而定（{{ data.year_ganzhi[0] }}为{{ ganYinyang(data.year_ganzhi[0]) }}）；日主阴阳即日干阴阳。</div>
          </div>

          <div class="know-card">
            <div class="know-head">十神速查（以日主为基准）</div>
            <div v-for="s in shishenTable" :key="s.name" class="ss-row">
              <span class="ss-name">{{ s.name }}</span>
              <span class="ss-rel">{{ s.rel }}</span>
              <span class="ss-desc">{{ s.desc }}</span>
            </div>
            <div class="cycle-note">四柱中天干、地支本气藏干相对日主的生克关系即为十神，月令本气十神定「格局」（如七杀格、正官格）。</div>
          </div>

          <div class="know-card">
            <div class="know-head">五行相生</div>
            <div class="cycle-line">
              <template v-for="(s, i) in shengCycle">
                <span :key="'a' + i" class="cycle-node" :style="eleStyle(s.from)">{{ s.from }}</span>
                <span :key="'b' + i" class="cycle-arrow">生</span>
                <span v-if="i === shengCycle.length - 1" :key="'c' + i" class="cycle-node" :style="eleStyle(s.to)">{{ s.to }}</span>
              </template>
            </div>
            <div class="cycle-note">{{ shengDesc }}</div>
          </div>

          <div class="know-card">
            <div class="know-head">五行相克</div>
            <div class="ke-list">
              <span v-for="k in keList" :key="k" class="ke-item">
                <b :style="eleStyle(k[0])">{{ k[0] }}</b> 克 <b :style="eleStyle(k[2])">{{ k[2] }}</b>
              </span>
            </div>
          </div>

          <div class="know-card">
            <div class="know-head">八卦基础</div>
            <div class="bagua-grid">
              <div v-for="g in baguaList" :key="g.name" class="bagua-item">
                <div class="bagua-symbol" :style="eleStyle(g.element)">{{ g.symbol }}</div>
                <div class="bagua-name" :style="eleStyle(g.element)">{{ g.name }}卦</div>
                <div class="bagua-meta">{{ g.element }} · {{ g.nature }}</div>
                <div class="bagua-meta muted">{{ g.direction }} · 代表{{ g.represent }}</div>
              </div>
            </div>
          </div>

          <div class="disclaimer">
            八字五行、纳音八卦源自中国传统干支历法与民俗文化，仅供娱乐参考，请勿作为决策依据。
          </div>
        </template>
      </div>
    </div>

    <van-popup v-model="showHourPicker" position="bottom" round get-container="body">
      <van-picker
        show-toolbar
        title="选择出生时辰"
        :columns="hourColumns"
        @confirm="onConfirmHour"
        @cancel="showHourPicker = false"
      />
    </van-popup>
  </van-popup>
</template>

<script>
import { Toast } from 'vant'
import { getBirthdayBaziReq, updateBirthdayReq } from '@/api/baby'

const ELE_COLORS = { '金': '#b8860b', '木': '#2e9e5b', '水': '#1e6fba', '火': '#e03e3e', '土': '#8c6239' }
const ELE_ORDER = ['金', '木', '水', '火', '土']

const ELEMENT_KNOWLEDGE = [
  { name: '金', direction: '西方', season: '秋季', colorName: '白', color: ELE_COLORS['金'], trigrams: '乾☰ 兑☱', organ: '肺、大肠', desc: '主收敛肃降，象征刚毅果断、重情重义。' },
  { name: '木', direction: '东方', season: '春季', colorName: '青', color: ELE_COLORS['木'], trigrams: '震☳ 巽☴', organ: '肝、胆', desc: '主生发条达，象征仁厚宽和、积极向上。' },
  { name: '水', direction: '北方', season: '冬季', colorName: '黑', color: ELE_COLORS['水'], trigrams: '坎☵', organ: '肾、膀胱', desc: '主滋润闭藏，象征智慧灵动、善于变通。' },
  { name: '火', direction: '南方', season: '夏季', colorName: '赤', color: ELE_COLORS['火'], trigrams: '离☲', organ: '心、小肠', desc: '主炎上光亮，象征热情守礼、光明磊落。' },
  { name: '土', direction: '中央', season: '长夏', colorName: '黄', color: ELE_COLORS['土'], trigrams: '艮☶ 坤☷', organ: '脾、胃', desc: '主承载生化，象征诚信厚重、包容稳健。' }
]

const SHENG_CYCLE = [
  { from: '金', to: '水' },
  { from: '水', to: '木' },
  { from: '木', to: '火' },
  { from: '火', to: '土' },
  { from: '土', to: '金' }
]
const SHENG_DESC = '金生水（金凝露成水）、水生木（水润泽养木）、木生火（木燃而生火）、火生土（火烬化为土）、土生金（土中蕴藏金）。'

const KE_LIST = ['金克木', '木克土', '土克水', '水克火', '火克金']

const GAN_TABLE = [
  { char: '甲', yy: '阳', ele: '木' }, { char: '乙', yy: '阴', ele: '木' },
  { char: '丙', yy: '阳', ele: '火' }, { char: '丁', yy: '阴', ele: '火' },
  { char: '戊', yy: '阳', ele: '土' }, { char: '己', yy: '阴', ele: '土' },
  { char: '庚', yy: '阳', ele: '金' }, { char: '辛', yy: '阴', ele: '金' },
  { char: '壬', yy: '阳', ele: '水' }, { char: '癸', yy: '阴', ele: '水' }
]

const ZHI_TABLE = [
  { char: '子', yy: '阳', ele: '水' }, { char: '丑', yy: '阴', ele: '土' },
  { char: '寅', yy: '阳', ele: '木' }, { char: '卯', yy: '阴', ele: '木' },
  { char: '辰', yy: '阳', ele: '土' }, { char: '巳', yy: '阴', ele: '火' },
  { char: '午', yy: '阳', ele: '火' }, { char: '未', yy: '阴', ele: '土' },
  { char: '申', yy: '阳', ele: '金' }, { char: '酉', yy: '阴', ele: '金' },
  { char: '戌', yy: '阳', ele: '土' }, { char: '亥', yy: '阴', ele: '水' }
]

const SHISHEN_TABLE = [
  { name: '比肩', rel: '同我 · 同性', desc: '自立自助，兄弟朋友，亦主竞争分财' },
  { name: '劫财', rel: '同我 · 异性', desc: '行动果断，善抓机遇，亦主破财是非' },
  { name: '食神', rel: '我生 · 同性', desc: '温和才艺，口福享受，表达流畅' },
  { name: '伤官', rel: '我生 · 异性', desc: '聪明叛逆，才华外露，不喜约束' },
  { name: '偏财', rel: '我克 · 同性', desc: '活络慷慨，偏门机遇之财，善交际' },
  { name: '正财', rel: '我克 · 异性', desc: '勤俭踏实，正当收入，重信守约' },
  { name: '七杀', rel: '克我 · 同性', desc: '魄力威严，抗压执行，亦主偏激好胜' },
  { name: '正官', rel: '克我 · 异性', desc: '正直自律，责任规则，名誉地位' },
  { name: '偏印', rel: '生我 · 同性', desc: '领悟力强，冷门专才，多思内省' },
  { name: '正印', rel: '生我 · 异性', desc: '仁慈庇护，学养名声，多得助力' }
]

const BAGUA_LIST = [
  { name: '乾', symbol: '☰', element: '金', nature: '天', direction: '西北', represent: '刚健' },
  { name: '兑', symbol: '☱', element: '金', nature: '泽', direction: '正西', represent: '喜悦' },
  { name: '离', symbol: '☲', element: '火', nature: '火', direction: '正南', represent: '光明' },
  { name: '震', symbol: '☳', element: '木', nature: '雷', direction: '正东', represent: '奋动' },
  { name: '巽', symbol: '☴', element: '木', nature: '风', direction: '东南', represent: '顺入' },
  { name: '坎', symbol: '☵', element: '水', nature: '水', direction: '正北', represent: '险陷' },
  { name: '艮', symbol: '☶', element: '土', nature: '山', direction: '东北', represent: '稳止' },
  { name: '坤', symbol: '☷', element: '土', nature: '地', direction: '西南', represent: '柔顺' }
]

// 十二时辰（取各时辰代表整点，避开 23 点晚子时换日争议）
const HOUR_OPTIONS = [
  { label: '子时 (23-01)', hour: 0 },
  { label: '丑时 (01-03)', hour: 2 },
  { label: '寅时 (03-05)', hour: 4 },
  { label: '卯时 (05-07)', hour: 6 },
  { label: '辰时 (07-09)', hour: 8 },
  { label: '巳时 (09-11)', hour: 10 },
  { label: '午时 (11-13)', hour: 12 },
  { label: '未时 (13-15)', hour: 14 },
  { label: '申时 (15-17)', hour: 16 },
  { label: '酉时 (17-19)', hour: 18 },
  { label: '戌时 (19-21)', hour: 20 },
  { label: '亥时 (21-23)', hour: 22 }
]

export default {
  name: 'BaziDialog',
  props: {
    visible: { type: Boolean, default: false },
    item: { type: Object, default: null }
  },
  data() {
    return {
      loading: false,
      data: null,
      hour: null,
      showHourPicker: false,
      sect: 2,
      activeDayun: 1,
      currentYear: new Date().getFullYear(),
      elementKnowledge: ELEMENT_KNOWLEDGE,
      shengCycle: SHENG_CYCLE,
      shengDesc: SHENG_DESC,
      keList: KE_LIST,
      baguaList: BAGUA_LIST,
      hourOptions: HOUR_OPTIONS,
      ganTable: GAN_TABLE,
      zhiTable: ZHI_TABLE,
      shishenTable: SHISHEN_TABLE
    }
  },
  computed: {
    title() {
      return this.item && this.item.name ? `八字五行 · ${this.item.name}` : '八字五行'
    },
    wuxingList() {
      if (!this.data) return []
      const counts = this.data.wuxing_count || {}
      const max = Math.max(1, ...ELE_ORDER.map(k => counts[k] || 0))
      return ELE_ORDER.map(name => {
        const count = counts[name] || 0
        return { name, count, color: ELE_COLORS[name], pct: Math.round((count / max) * 100) }
      })
    },
    hourColumns() {
      return this.hourOptions.map(o => o.label)
    },
    hourText() {
      if (this.hour === null || !this.data) return ''
      const opt = this.hourOptions.find(o => o.hour === this.hour)
      return opt ? opt.label.split(' ')[0] : ''
    }
  },
  watch: {
    visible(v) {
      if (v) {
        // 打开时从记录回填已保存的出生时辰
        this.hour = (this.item && typeof this.item.birth_hour === 'number') ? this.item.birth_hour : null
        this.fetchData()
      }
    }
  },
  methods: {
    onPopupInput(v) {
      this.$emit('update:visible', v)
    },
    close() {
      this.$emit('update:visible', false)
    },
    eleStyle(ele) {
      return { color: ELE_COLORS[ele] || '#1f2329' }
    },
    ganYinyang(char) {
      const g = this.ganTable.find(o => o.char === char)
      return g ? g.yy + g.ele : char
    },
    openHourPicker() {
      this.showHourPicker = true
    },
    onConfirmHour(value, index) {
      this.hour = this.hourOptions[index].hour
      this.showHourPicker = false
      this.persistHour()
      this.fetchData()
    },
    clearHour() {
      this.hour = null
      this.persistHour()
      this.fetchData()
    },
    persistHour() {
      if (!this.item || !this.item.id) return
      this.item.birth_hour = this.hour
      updateBirthdayReq({ id: this.item.id, birth_hour: this.hour }).catch(() => {
        Toast('时辰保存失败')
      })
    },
    fetchData() {
      if (!this.item || !this.item.id) return
      this.loading = true
      const params = { id: this.item.id, sect: this.sect }
      if (this.hour !== null) params.hour = this.hour
      getBirthdayBaziReq(params).then(res => {
        if (res && res.code === 200) {
          this.data = res.data
          // 默认选中当前年份所在的大运
          if (this.data.yun && this.data.yun.dayuns && this.data.yun.dayuns.length) {
            const y = this.currentYear
            const idx = this.data.yun.dayuns.findIndex(d => y >= d.start_year && y <= d.end_year)
            this.activeDayun = idx >= 0 ? idx : Math.min(1, this.data.yun.dayuns.length - 1)
          }
        } else {
          Toast((res && res.msg) || '测算失败')
          this.close()
        }
      }).catch(() => {
        Toast('测算失败')
        this.close()
      }).finally(() => {
        this.loading = false
      })
    },
    setSect(s) {
      if (this.sect === s) return
      this.sect = s
      this.fetchData()
    },
    setGender(g) {
      if (!this.item || !this.item.id) return
      updateBirthdayReq({ id: this.item.id, gender: g }).then(() => {
        this.item.gender = g
        this.fetchData()
      }).catch(() => {
        Toast('性别保存失败')
      })
    }
  }
}
</script>

<style scoped>
.bazi-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}
.bazi-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 12px 24px;
}
.loading-wrap {
  padding: 60px 0;
  display: flex;
  justify-content: center;
}
.info-card {
  background: linear-gradient(135deg, #fff5f8 0%, #fffdfa 100%);
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 8px 22px rgba(31, 35, 41, 0.06);
}
.info-name {
  font-size: 18px;
  font-weight: 800;
  color: #1f2329;
  display: flex;
  align-items: center;
  gap: 8px;
}
.zodiac-tag {
  font-size: 12px;
  font-weight: 600;
  color: #ff4d7d;
  background: rgba(255, 77, 125, 0.10);
  border: 1px solid rgba(255, 77, 125, 0.20);
  border-radius: 999px;
  padding: 2px 10px;
}
.element-tag {
  background: rgba(255, 255, 255, 0.9);
}
.info-line {
  margin-top: 8px;
  font-size: 12px;
  color: #646a73;
}
.info-line.muted {
  color: #8b949e;
}
.section-title {
  margin: 16px 2px 8px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2329;
}
.section-sub {
  font-size: 11px;
  font-weight: 400;
  color: #8b949e;
}
.pillars {
  display: flex;
  gap: 8px;
}
.pillar {
  flex: 1;
  background: #fff;
  border-radius: 14px;
  padding: 10px 4px;
  text-align: center;
  box-shadow: 0 6px 16px rgba(31, 35, 41, 0.06);
}
.pillar-empty {
  background: #fbfbfc;
  border: 1px dashed rgba(31, 35, 41, 0.14);
  box-shadow: none;
}
.pillar-label {
  font-size: 11px;
  color: #8b949e;
  margin-bottom: 6px;
}
.pillar-char {
  font-size: 22px;
  font-weight: 800;
  line-height: 30px;
}
.pillar-char i {
  display: block;
  font-style: normal;
  font-size: 10px;
  font-weight: 400;
  color: #8b949e;
}
.pillar-nayin {
  margin-top: 6px;
  font-size: 10px;
  color: #646a73;
  white-space: nowrap;
}
.pillar-hide {
  margin-top: 2px;
  font-size: 9px;
  color: #a1a7af;
  white-space: nowrap;
}
.chip-geju {
  color: #8a5a00;
  background: rgba(184, 134, 11, 0.10);
  border: 1px solid rgba(184, 134, 11, 0.30);
}
.detail-card {
  margin-top: 10px;
}
.detail-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed rgba(31, 35, 41, 0.06);
}
.detail-row:last-child {
  border-bottom: none;
}
.detail-label {
  flex-shrink: 0;
  width: 34px;
  font-size: 12px;
  font-weight: 700;
  color: #8a5a00;
}
.detail-value {
  font-size: 13px;
  font-weight: 700;
  color: #1f2329;
}
.detail-sub {
  margin-left: 8px;
  font-style: normal;
  font-size: 10px;
  font-weight: 400;
  color: #a1a7af;
}
.gz-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.gz-grid.zhi {
  margin-bottom: 10px;
}
.gz-item {
  flex: 1;
  min-width: calc(20% - 5px);
  background: #fafbfc;
  border-radius: 8px;
  text-align: center;
  padding: 6px 2px;
}
.gz-item b {
  display: block;
  font-size: 15px;
}
.gz-item span {
  display: block;
  font-size: 9px;
  color: #8b949e;
  white-space: nowrap;
}
.ss-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px dashed rgba(31, 35, 41, 0.05);
}
.ss-row:last-of-type {
  border-bottom: none;
}
.ss-name {
  flex-shrink: 0;
  width: 34px;
  font-size: 12px;
  font-weight: 700;
  color: #8a5a00;
}
.ss-rel {
  flex-shrink: 0;
  width: 74px;
  font-size: 10px;
  color: #8b949e;
}
.ss-desc {
  flex: 1;
  font-size: 11px;
  color: #41464e;
  line-height: 16px;
}
.sect-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 0 10px;
}
.sect-label {
  font-size: 12px;
  font-weight: 700;
  color: #41464e;
}
.sect-chip {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f2f3f5;
  color: #646a73;
}
.sect-chip.active {
  background: rgba(255, 122, 154, 0.12);
  color: #ff5c8a;
  font-weight: 700;
}
.sect-note {
  width: 100%;
  font-size: 10px;
  color: #a1a7af;
}
.yun-start {
  font-size: 11px;
  color: #646a73;
  margin-bottom: 10px;
}
.yun-warn {
  display: block;
  color: #ff976a;
}
.dayun-scroll {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 4px;
  -webkit-overflow-scrolling: touch;
}
.dayun-scroll::-webkit-scrollbar {
  display: none;
}
.dayun-chip {
  flex-shrink: 0;
  min-width: 64px;
  text-align: center;
  background: #fafbfc;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 6px 8px;
}
.dayun-chip b {
  display: block;
  font-size: 14px;
  color: #1f2329;
}
.dayun-chip span {
  display: block;
  font-size: 9px;
  color: #8b949e;
  white-space: nowrap;
}
.dayun-chip.active {
  background: rgba(255, 122, 154, 0.10);
  border-color: rgba(255, 92, 138, 0.45);
}
.dayun-chip.active b {
  color: #ff5c8a;
}
.liunian-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 5px;
}
.liunian-item {
  text-align: center;
  background: #fafbfc;
  border-radius: 6px;
  padding: 5px 2px;
}
.liunian-item b {
  display: block;
  font-size: 12px;
  color: #1f2329;
}
.liunian-item span {
  display: block;
  font-size: 9px;
  color: #8b949e;
}
.liunian-item.now {
  background: rgba(255, 122, 154, 0.12);
}
.liunian-item.now b {
  color: #ff5c8a;
}
.yun-tip {
  font-size: 12px;
  color: #646a73;
  margin-bottom: 10px;
}
.gender-btns {
  display: flex;
  gap: 10px;
}
.gender-btn {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  border-radius: 999px;
  background: rgba(255, 122, 154, 0.10);
  color: #ff5c8a;
  font-size: 13px;
  font-weight: 700;
}
.pillar-tips {
  font-size: 11px;
  color: #b0b6bf;
  line-height: 18px;
  padding: 12px 0;
}
.hour-bar {
  margin-top: 10px;
  background: #fff;
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.hour-label {
  color: #8b949e;
}
.hour-value {
  color: #1f2329;
  font-weight: 700;
}
.hour-value.muted {
  color: #b0b6bf;
  font-weight: 400;
  flex: 1;
}
.hour-value + .hour-action {
  margin-left: auto;
}
.hour-action {
  color: #ff4d7d;
  font-weight: 600;
}
.hour-action.clear {
  color: #8b949e;
}
.wx-card {
  background: #fff;
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 6px 16px rgba(31, 35, 41, 0.06);
}
.wx-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.wx-name {
  width: 20px;
  font-size: 13px;
  font-weight: 800;
}
.wx-track {
  flex: 1;
  height: 10px;
  border-radius: 999px;
  background: rgba(31, 35, 41, 0.05);
  overflow: hidden;
}
.wx-bar {
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
}
.wx-count {
  width: 16px;
  text-align: right;
  font-size: 12px;
  font-weight: 700;
  color: #1f2329;
}
.wx-summary {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.wx-chip {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(31, 35, 41, 0.08);
}
.chip-warn {
  color: #d46b08;
  background: #fff7e6;
  border-color: rgba(212, 107, 8, 0.25);
}
.chip-ok {
  color: #2e9e5b;
  background: #f0faf4;
  border-color: rgba(46, 158, 91, 0.25);
}
.know-card {
  background: #fff;
  border-radius: 14px;
  padding: 12px;
  margin-bottom: 10px;
  box-shadow: 0 6px 16px rgba(31, 35, 41, 0.06);
}
.know-head {
  font-size: 13px;
  font-weight: 700;
  color: #1f2329;
  margin-bottom: 10px;
}
.ele-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ele-item {
  width: calc(50% - 4px);
  background: #fafbfc;
  border-radius: 12px;
  padding: 10px;
  box-sizing: border-box;
}
.ele-head {
  font-size: 15px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ele-trigram {
  font-size: 13px;
  letter-spacing: 2px;
}
.ele-meta {
  margin-top: 4px;
  font-size: 11px;
  color: #646a73;
}
.ele-desc {
  margin-top: 4px;
  font-size: 11px;
  color: #41464e;
  line-height: 16px;
}
.ele-organ {
  margin-top: 4px;
  font-size: 10px;
  color: #8b949e;
}
.cycle-line {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: wrap;
}
.cycle-node {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: rgba(31, 35, 41, 0.04);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 800;
}
.cycle-arrow {
  font-size: 11px;
  color: #8b949e;
}
.cycle-note {
  margin-top: 10px;
  font-size: 11px;
  color: #646a73;
  line-height: 17px;
}
.ke-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ke-item {
  font-size: 12px;
  color: #41464e;
  background: #fafbfc;
  border-radius: 999px;
  padding: 4px 10px;
}
.bagua-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.bagua-item {
  width: calc(25% - 6px);
  background: #fafbfc;
  border-radius: 12px;
  padding: 10px 4px;
  text-align: center;
  box-sizing: border-box;
}
.bagua-symbol {
  font-size: 22px;
  line-height: 26px;
}
.bagua-name {
  font-size: 12px;
  font-weight: 700;
  margin-top: 2px;
}
.bagua-meta {
  font-size: 10px;
  color: #646a73;
  margin-top: 2px;
  white-space: nowrap;
}
.bagua-meta.muted {
  color: #a1a7af;
}
.disclaimer {
  margin-top: 4px;
  font-size: 10px;
  color: #a1a7af;
  text-align: center;
  line-height: 15px;
}
</style>

<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>✅ 已通过三元组统计与图谱同步</h2>
      <div style="margin-left: auto; display: flex; gap: 8px;">
        <el-button size="small" @click="loadAll" :loading="loading">刷新</el-button>
        <el-button size="small" type="primary" @click="syncNeo4j" :loading="syncing">同步到 Neo4j</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="kg-card" style="margin-bottom: 20px;">
      <div class="kg-stat-row" style="display: flex; gap: 20px; flex-wrap: wrap;">
        <div class="kg-stat-item" style="flex: 1; min-width: 140px; text-align: center; padding: 16px; background: #f0f9ff; border-radius: 8px; border: 1px solid #d0e8ff;">
          <div style="font-size: 28px; font-weight: 700; color: #409eff;">{{ stats.total || 0 }}</div>
          <div style="font-size: 13px; color: #606266; margin-top: 4px;">总数</div>
        </div>
        <div class="kg-stat-item" style="flex: 1; min-width: 140px; text-align: center; padding: 16px; background: #f0f9eb; border-radius: 8px; border: 1px solid #d4edda;">
          <div style="font-size: 28px; font-weight: 700; color: #67c23a;">{{ stats.recent_7_days || 0 }}</div>
          <div style="font-size: 13px; color: #606266; margin-top: 4px;">近7天新增</div>
        </div>
        <div class="kg-stat-item" style="flex: 1; min-width: 140px; text-align: center; padding: 16px; background: #fdf6ec; border-radius: 8px; border: 1px solid #faecd8;">
          <div style="font-size: 28px; font-weight: 700; color: #e6a23c;">{{ engineCount }}</div>
          <div style="font-size: 13px; color: #606266; margin-top: 4px;">引擎数</div>
        </div>
        <div class="kg-stat-item" style="flex: 1; min-width: 140px; text-align: center; padding: 16px; background: #fef0f0; border-radius: 8px; border: 1px solid #fde2e2;">
          <div style="font-size: 28px; font-weight: 700; color: #f56c6c;">{{ relationCount }}</div>
          <div style="font-size: 13px; color: #606266; margin-top: 4px;">关系类型数</div>
        </div>
      </div>
    </div>

    <!-- 图表区 -->
    <div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">
      <!-- 关系类型分布（CSS 条形图） -->
      <div class="kg-card" style="flex: 1; min-width: 360px;">
        <h3 style="margin: 0 0 16px;">📈 关系类型分布</h3>
        <div v-if="relationEntries.length" style="display: flex; flex-direction: column; gap: 8px;">
          <div v-for="item in relationEntries" :key="item.name" style="display: flex; align-items: center; gap: 8px;">
            <div style="width: 120px; font-size: 13px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" :title="item.name">{{ item.name }}</div>
            <div style="flex: 1; background: #f0f0f0; border-radius: 4px; height: 22px; position: relative;">
              <div :style="{
                width: (item.pct) + '%',
                height: '100%',
                borderRadius: '4px',
                background: relationBarColor(item.pct),
                transition: 'width 0.5s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: '6px',
                fontSize: '12px',
                color: '#fff',
                fontWeight: 600,
              }">{{ item.count }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无数据" :image-size="60" />
      </div>

      <!-- 引擎分布（CSS 饼图替代） -->
      <div class="kg-card" style="flex: 1; min-width: 360px;">
        <h3 style="margin: 0 0 16px;">🥧 引擎分布</h3>
        <div v-if="engineEntries.length" style="display: flex; align-items: center; gap: 24px; flex-wrap: wrap;">
          <!-- CSS 圆环图 -->
          <div style="position: relative; width: 160px; height: 160px;">
            <div :style="donutStyle" style="width: 100%; height: 100%; border-radius: 50%;"></div>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center;">
              <div style="font-size: 24px; font-weight: 700;">{{ stats.total || 0 }}</div>
              <div style="font-size: 12px; color: #909399;">总计</div>
            </div>
          </div>
          <!-- 图例 -->
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <div v-for="item in engineEntries" :key="item.name" style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
              <div :style="{ width: '12px', height: '12px', borderRadius: '2px', background: item.color }"></div>
              <span>{{ item.name }}</span>
              <span style="color: #909399;">({{ item.count }})</span>
              <span style="color: #c0c4cc; font-size: 12px;">{{ item.pct }}%</span>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无数据" :image-size="60" />
      </div>
    </div>

    <!-- 三元组列表 -->
    <div class="kg-card">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
        <h3 style="margin: 0;">📋 三元组列表</h3>
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索主体/客体"
            size="small"
            style="width: 200px;"
            clearable
            @keyup.enter="doSearch"
          />
          <el-select v-model="filterRelation" placeholder="关系筛选" size="small" style="width: 160px;" clearable @change="doSearch">
            <el-option v-for="r in relationOptions" :key="r" :label="r" :value="r" />
          </el-select>
          <el-button size="small" type="primary" @click="doSearch">搜索</el-button>
        </div>
      </div>
      <el-table :data="triples" stripe style="width: 100%" max-height="500" empty-text="暂无已通过的三元组">
        <el-table-column prop="subject" label="主体" min-width="140" show-overflow-tooltip />
        <el-table-column prop="predicate" label="关系" width="140" show-overflow-tooltip />
        <el-table-column prop="object" label="客体" min-width="140" show-overflow-tooltip />
        <el-table-column prop="extraction_method" label="引擎" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ row.extraction_method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="llm_confidence" label="置信度" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.llm_confidence != null" :type="row.llm_confidence >= 90 ? 'success' : row.llm_confidence >= 70 ? 'warning' : 'danger'" size="small">
              {{ row.llm_confidence.toFixed(0) }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" text @click="deleteTriple(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display: flex; justify-content: flex-end; margin-top: 16px;">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="totalTriples"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          size="small"
          @current-change="loadTriples"
          @size-change="loadTriples"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { passedTriplesApi, extractApi } from '../api'

const route = useRoute()
const projectId = route.params.id

const loading = ref(false)
const syncing = ref(false)
const stats = ref({})
const triples = ref([])
const totalTriples = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchKeyword = ref('')
const filterRelation = ref('')

const ENGINE_COLORS = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9c27b0', '#00bcd4', '#ff9800']

const engineEntries = computed(() => {
  const data = stats.value.by_engine || {}
  const total = Object.values(data).reduce((s, v) => s + v, 0) || 1
  return Object.entries(data)
    .map(([name, count], i) => ({
      name,
      count,
      pct: Math.round((count / total) * 100),
      color: ENGINE_COLORS[i % ENGINE_COLORS.length],
    }))
    .sort((a, b) => b.count - a.count)
})

const engineCount = computed(() => Object.keys(stats.value.by_engine || {}).length)

const relationEntries = computed(() => {
  const data = stats.value.by_relation || {}
  const max = Math.max(...Object.values(data), 1)
  return Object.entries(data)
    .map(([name, count]) => ({
      name,
      count,
      pct: Math.round((count / max) * 100),
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 20)
})

const relationCount = computed(() => Object.keys(stats.value.by_relation || {}).length)

const relationOptions = computed(() => Object.keys(stats.value.by_relation || {}).sort())

const donutStyle = computed(() => {
  const entries = engineEntries.value
  if (!entries.length) return { background: '#f0f0f0' }
  const total = entries.reduce((s, e) => s + e.count, 0) || 1
  let cumulative = 0
  const stops = []
  for (const e of entries) {
    const start = (cumulative / total) * 360
    cumulative += e.count
    const end = (cumulative / total) * 360
    stops.push(`${e.color} ${start}deg ${end}deg`)
  }
  return { background: `conic-gradient(${stops.join(', ')})` }
})

function relationBarColor(pct) {
  if (pct >= 75) return '#409eff'
  if (pct >= 50) return '#67c23a'
  if (pct >= 25) return '#e6a23c'
  return '#f56c6c'
}

function formatDate(s) {
  if (!s) return ''
  let str = String(s)
  if (!str.endsWith('Z') && !str.includes('+') && !str.match(/\d{2}:\d{2}:\d{2}\.\d/)) {
    str = str + 'Z'
  }
  const d = new Date(str)
  if (isNaN(d)) return s
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

async function loadStats() {
  try {
    const res = await passedTriplesApi.stats(projectId)
    stats.value = res || {}
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

async function loadTriples() {
  try {
    const res = await passedTriplesApi.list(projectId, {
      page: currentPage.value,
      page_size: pageSize.value,
      keyword: searchKeyword.value,
      relation: filterRelation.value,
    })
    triples.value = res.items || []
    totalTriples.value = res.total || 0
  } catch (e) {
    console.error('加载三元组列表失败', e)
  }
}

async function loadAll() {
  loading.value = true
  await Promise.all([loadStats(), loadTriples()])
  loading.value = false
}

function doSearch() {
  currentPage.value = 1
  loadTriples()
}

async function deleteTriple(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除三元组「${row.subject} → ${row.predicate} → ${row.object}」?`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await extractApi.deleteTriple(row.id)
    ElMessage.success('删除成功')
    await Promise.all([loadStats(), loadTriples()])
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

async function syncNeo4j() {
  try {
    await ElMessageBox.confirm(
      `确认将所有已通过的三元组同步到 Neo4j?`,
      '同步确认',
      { type: 'info', confirmButtonText: '同步', cancelButtonText: '取消' }
    )
    syncing.value = true
    const res = await passedTriplesApi.syncNeo4j(projectId)
    if (res.failed > 0) {
      ElMessage.warning(`同步完成: 成功 ${res.synced} 条, 失败 ${res.failed} 条${res.error ? ' (' + res.error + ')' : ''}`)
    } else {
      ElMessage.success(`同步成功: ${res.synced} 条三元组已同步到 Neo4j`)
    }
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    syncing.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

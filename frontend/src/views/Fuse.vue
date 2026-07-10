<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push('/projects')" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>融合中心</h2>
      <span style="margin-left: 12px; color: #95a5a6; font-size: 13px;">全局跨项目实体融合 · Neo4j 图谱管理</span>
      <div style="margin-left: auto; display: flex; gap: 12px; align-items: center;">
        <el-popover trigger="click" width="420" @before-enter="loadQuickModel">
          <template #reference>
            <el-button size="small">融合模型: {{ quickForm.model_name || '未配置' }}</el-button>
          </template>
          <div style="padding: 12px;">
            <h4 style="margin: 0 0 12px;">配置 融合阶段 模型（全局）</h4>
            <el-form label-width="80px" size="small">
              <el-form-item label="服务商">
                <el-select v-model="quickForm.api_provider" style="width: 100%;">
                  <el-option label="OpenAI" value="OPENAI" />
                  <el-option label="Anthropic" value="ANTHROPIC" />
                  <el-option label="DeepSeek" value="DEEPSEEK" />
                  <el-option label="Qwen" value="QWEN" />
                </el-select>
              </el-form-item>
              <el-form-item label="Base URL">
                <el-input v-model="quickForm.base_url" placeholder="https://api.openai.com/v1" />
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="quickForm.api_key" type="password" show-password placeholder="留空不更新" />
              </el-form-item>
              <el-form-item label="模型名">
                <el-input v-model="quickForm.model_name" placeholder="gpt-4o" />
              </el-form-item>
            </el-form>
            <el-button type="primary" size="small" @click="saveQuickModel" style="width: 100%; margin-top: 8px;">保存到选中项目</el-button>
          </div>
        </el-popover>
      </div>
    </div>

    <!-- 项目选择 + 融合操作 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">项目选择与自动融合</h3>
      <div style="display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 16px;">
        <div>
          <label style="display: block; font-size: 13px; color: #606266; margin-bottom: 6px;">选择参与融合的项目（可多选）</label>
          <el-select v-model="selectedProjectIds" multiple placeholder="选择项目" style="width: 480px;" size="default">
            <el-option v-for="p in allProjects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </div>
      </div>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <el-button type="primary" @click="autoFuseMulti" :loading="fusing" :disabled="!selectedProjectIds.length">
          自动融合选中项目
        </el-button>
        <el-button @click="loadSuggestionsMulti" :disabled="!selectedProjectIds.length">查看融合建议</el-button>
        <el-button type="success" @click="llmDisambiguateMulti" :loading="llming" :disabled="!suggestions.length">
          LLM 辅助消歧
        </el-button>
      </div>
      <p v-if="autoClusters.length" style="margin-top: 12px; color: #27ae60;">
        自动发现 {{ autoClusters.length }} 个实体聚类 (相似度 > 95%)
      </p>
    </div>

    <!-- 融合建议列表 -->
    <div v-if="suggestions.length" class="kg-card">
      <h3 style="margin-bottom: 16px;">融合建议 ({{ suggestions.length }} 对)</h3>
      <el-table :data="suggestions" stripe style="width: 100%" max-height="400">
        <el-table-column prop="entity_1" label="实体 1" />
        <el-table-column prop="entity_2" label="实体 2" />
        <el-table-column prop="similarity" label="相似度" width="100">
          <template #default="{ row }">{{ row.similarity?.toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="suggestion" label="建议" width="180">
          <template #default="{ row }">
            <el-tag v-if="row.suggestion === 'LLM_SUGGEST_MERGE'" type="success">LLM建议合并</el-tag>
            <el-tag v-else-if="row.suggestion === 'LLM_SUGGEST_KEEP_SEPARATE'" type="info">LLM建议保留</el-tag>
            <el-tag v-else type="warning">需人工确认</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="project_id" label="所属项目" width="150">
          <template #default="{ row }">
            {{ projectName(row.project_id) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="mergePair(row)">合并</el-button>
            <el-button size="small" @click="skipSuggestion(row)">跳过</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Neo4j 管理 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">Neo4j 图谱管理</h3>
      <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
        <el-button type="warning" @click="syncNeo4jMulti" :loading="syncing" :disabled="!selectedProjectIds.length">
          同步到 Neo4j（项目隔离）
        </el-button>
        <el-button type="primary" @click="syncNeo4jMerged" :loading="syncingMerged" :disabled="!selectedProjectIds.length">
          合并同步到 Neo4j（统一图谱）
        </el-button>
        <el-button type="success" @click="viewNeo4jGraph" :loading="viewingGraph">查看图谱可视化</el-button>
        <el-button type="danger" plain @click="clearNeo4j" :loading="clearing">清空 Neo4j 图谱</el-button>
      </div>
      <p style="margin-top: 8px; color: #95a5a6; font-size: 13px;">
        <strong>项目隔离</strong>: 各项目分别写入，通过 project_id 属性隔离<br/>
        <strong>统一图谱</strong>: 跨项目实体合并去重后写入统一图谱（MergedEntity 标签）<br/>
        同步后可在 <a :href="neo4jUrl" target="_blank">{{ neo4jUrl }}</a> 查看图谱
      </p>
    </div>

    <!-- Neo4j 图谱可视化弹窗 -->
    <el-dialog v-model="graphDialogVisible" title="Neo4j 图谱可视化" width="90%" top="3vh" @opened="renderGraphDialog">
      <div style="display: flex; gap: 12px; margin-bottom: 12px; align-items: center;">
        <span style="font-size: 13px; color: #606266;">节点: {{ neo4jGraphData.node_count }} | 关系: {{ neo4jGraphData.edge_count }}</span>
        <el-button size="small" @click="refreshNeo4jGraph">刷新</el-button>
        <el-radio-group v-model="graphLayout" size="small" @change="renderGraphDialog">
          <el-radio-button value="force">力导向</el-radio-button>
          <el-radio-button value="circular">环形</el-radio-button>
          <el-radio-button value="grid">网格</el-radio-button>
        </el-radio-group>
      </div>
      <div ref="neo4jGraphContainer" style="width: 100%; height: 70vh; background: #fafbfc; border-radius: 8px; border: 1px solid #eee;"></div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fusionApi, exportApi, llmConfigApi } from '../api'
import api from '../api'

const allProjects = ref([])
const selectedProjectIds = ref([])
const suggestions = ref([])
const autoClusters = ref([])
const fusing = ref(false)
const llming = ref(false)
const syncing = ref(false)
const syncingMerged = ref(false)
const clearing = ref(false)
const viewingGraph = ref(false)
const graphDialogVisible = ref(false)
const neo4jGraphData = ref({ nodes: [], edges: [], node_count: 0, edge_count: 0 })
const neo4jGraphContainer = ref(null)
const graphLayout = ref('force')
const quickForm = reactive({ api_provider: 'OPENAI', base_url: '', api_key: '', model_name: '' })

// Neo4j Browser 地址：基于当前主机动态生成，避免硬编码 localhost
const neo4jUrl = `http://${window.location.hostname}:7474`

let neo4jGraph = null

const COLOR_PALETTE = [
  '#5B8FF9', '#61DDAA', '#F6BD16', '#E8684A', '#6DC8EC',
  '#9270CA', '#FF9D4D', '#269A99', '#FF99C3', '#5AD8A6',
]

onMounted(async () => {
  try {
    const res = await api.get('/projects/')
    allProjects.value = res || []
  } catch (e) {
    ElMessage.error('加载项目列表失败: ' + (e.response?.data?.detail || e.message))
  }
})

function projectName(pid) {
  const p = allProjects.value.find(x => x.id === pid)
  return p ? p.name : pid?.slice(0, 8) || '-'
}

// ==================== 融合 ====================

async function autoFuseMulti() {
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择至少一个项目')
    return
  }
  fusing.value = true
  try {
    const res = await fusionApi.autoFuseMulti(selectedProjectIds.value)
    ElMessage.success(`${res.message}: ${res.fused_count} 条三元组, ${res.entities_created} 个实体, ${res.auto_clusters} 个自动聚类`)
  } catch (e) {
    ElMessage.error('融合失败: ' + (e.response?.data?.detail || ''))
  } finally {
    fusing.value = false
  }
}

async function loadSuggestionsMulti() {
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择至少一个项目')
    return
  }
  suggestions.value = []
  autoClusters.value = []
  for (const pid of selectedProjectIds.value) {
    try {
      const res = await fusionApi.suggestions(pid)
      const sugg = (res.suggestions || []).map(s => ({ ...s, project_id: pid }))
      suggestions.value.push(...sugg)
      autoClusters.value.push(...(res.auto_clusters || []))
    } catch (e) {
      ElMessage.error(`加载项目 ${projectName(pid)} 融合建议失败: ` + (e.response?.data?.detail || e.message))
    }
  }
  if (autoClusters.value.length) {
    ElMessage.info(`共发现 ${autoClusters.value.length} 个实体聚类`)
  }
  if (!suggestions.value.length) {
    ElMessage.info('暂无需人工确认的融合建议')
  }
}

async function llmDisambiguateMulti() {
  if (!suggestions.value.length) return
  llming.value = true
  try {
    // 对每个项目分别消歧
    const projectIds = [...new Set(suggestions.value.map(s => s.project_id))]
    const allDecisions = []
    for (const pid of projectIds) {
      try {
        const res = await fusionApi.llmDisambiguate(pid)
        if (res.decisions?.length) {
          const decisions = res.decisions.map(d => ({ ...d, project_id: pid }))
          allDecisions.push(...decisions)
        }
      } catch (e) {
        ElMessage.error(`项目 ${projectName(pid)} LLM 消歧失败: ` + (e.response?.data?.detail || e.message))
      }
    }
    if (allDecisions.length) {
      suggestions.value = allDecisions
      ElMessage.success(`LLM 消歧完成: ${allDecisions.length} 对`)
    } else {
      ElMessage.info('无需消歧或 LLM 未配置')
    }
  } finally {
    llming.value = false
  }
}

async function mergePair(row) {
  try {
    await fusionApi.merge(row.entity_1, row.entity_2, row.entity_1, row.project_id)
    ElMessage.success('合并成功')
    suggestions.value = suggestions.value.filter(s => !(s.entity_2 === row.entity_2 && s.project_id === row.project_id))
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.response?.data?.detail || ''))
  }
}

function skipSuggestion(row) {
  suggestions.value = suggestions.value.filter(s => !(s.entity_2 === row.entity_2 && s.project_id === row.project_id))
}

// ==================== 模型配置 ====================

async function loadQuickModel() {
  if (!selectedProjectIds.value.length) return
  try {
    const configs = await llmConfigApi.list(selectedProjectIds.value[0])
    const cfg = (configs || []).find(c => c.pipeline_stage === 'FUSION')
    if (cfg) {
      quickForm.api_provider = cfg.api_provider || 'OPENAI'
      quickForm.base_url = cfg.base_url || ''
      quickForm.model_name = cfg.model_name || ''
    }
  } catch (e) {
    ElMessage.error('加载融合模型配置失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveQuickModel() {
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择项目')
    return
  }
  try {
    // 保存到所有选中项目
    for (const pid of selectedProjectIds.value) {
      const configs = await llmConfigApi.list(pid)
      const configList = configs || []
      const existing = configList.find(c => c.pipeline_stage === 'FUSION')
      if (existing) {
        existing.api_provider = quickForm.api_provider
        existing.base_url = quickForm.base_url
        existing.model_name = quickForm.model_name
        if (quickForm.api_key) existing.api_key = quickForm.api_key
      } else {
        configList.push({
          pipeline_stage: 'FUSION',
          api_provider: quickForm.api_provider,
          base_url: quickForm.base_url,
          api_key: quickForm.api_key,
          model_name: quickForm.model_name,
        })
      }
      await llmConfigApi.update(pid, configList)
    }
    ElMessage.success(`模型配置已保存到 ${selectedProjectIds.value.length} 个项目`)
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || ''))
  }
}

// ==================== Neo4j ====================

async function syncNeo4jMulti() {
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择至少一个项目')
    return
  }
  syncing.value = true
  try {
    let totalRels = 0
    let errors = []
    for (const pid of selectedProjectIds.value) {
      try {
        const res = await exportApi.neo4jSync(pid)
        if (res.error) {
          errors.push(`${projectName(pid)}: ${res.error}`)
        } else if (res.relations !== undefined) {
          totalRels += res.relations
        } else if (res.note) {
          errors.push(`Neo4j 驱动未安装`)
          break
        }
      } catch (e) {
        errors.push(`${projectName(pid)}: ${e.response?.data?.detail || e.message}`)
      }
    }
    if (errors.length) {
      ElMessage.warning(`部分失败: ${errors.join('; ')}`)
    } else {
      ElMessage.success(`同步完成: ${totalRels} 条关系`)
    }
  } finally {
    syncing.value = false
  }
}

async function syncNeo4jMerged() {
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择至少一个项目')
    return
  }
  syncingMerged.value = true
  try {
    const body = { project_ids: selectedProjectIds.value }
    const res = await fusionApi.neo4jSyncMerged(body)
    ElMessage.success(res.message)
  } catch (e) {
    ElMessage.error('合并同步失败: ' + (e.response?.data?.detail || ''))
  } finally {
    syncingMerged.value = false
  }
}

async function viewNeo4jGraph() {
  viewingGraph.value = true
  try {
    await refreshNeo4jGraph()
    graphDialogVisible.value = true
  } finally {
    viewingGraph.value = false
  }
}

async function refreshNeo4jGraph() {
  try {
    const res = await fusionApi.neo4jGraph(500)
    neo4jGraphData.value = res
    if (graphDialogVisible.value) {
      await nextTick()
      renderGraphDialog()
    }
  } catch (e) {
    ElMessage.error('加载图谱失败: ' + (e.response?.data?.detail || ''))
  }
}

async function clearNeo4j() {
  try {
    await ElMessageBox.confirm(
      '确定要清空 Neo4j 中所有节点和关系吗？此操作不可恢复！',
      '危险操作确认',
      { type: 'error', confirmButtonText: '确认清空', cancelButtonText: '取消' }
    )
  } catch (e) {
    return
  }
  clearing.value = true
  try {
    const res = await fusionApi.neo4jClear()
    ElMessage.success(`${res.message}: ${res.deleted_nodes} 节点, ${res.deleted_rels} 关系`)
    neo4jGraphData.value = { nodes: [], edges: [], node_count: 0, edge_count: 0 }
  } catch (e) {
    ElMessage.error('清空失败: ' + (e.response?.data?.detail || ''))
  } finally {
    clearing.value = false
  }
}

function renderGraphDialog() {
  if (!neo4jGraphContainer.value) return
  import('@antv/g6').then((G6) => {
    if (neo4jGraph) {
      neo4jGraph.destroy()
      neo4jGraph = null
    }
    const data = neo4jGraphData.value
    if (!data.nodes?.length) return

    // 按项目分组着色
    const projectColors = {}
    let ci = 0
    data.nodes.forEach(n => {
      const pid = n.project_id || '_default'
      if (!projectColors[pid]) {
        projectColors[pid] = COLOR_PALETTE[ci % COLOR_PALETTE.length]
        ci++
      }
    })

    const g6Nodes = data.nodes.map(n => ({
      id: n.id,
      label: (n.label || n.id).substring(0, 16),
      style: { fill: projectColors[n.project_id || '_default'], stroke: '#fff', lineWidth: 2 },
      labelCfg: { position: 'bottom', offset: 6, style: { fill: '#333', fontSize: 10 } },
    }))

    const g6Edges = data.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label || '',
      style: { stroke: '#ccc', lineWidth: 1, endArrow: { path: G6.default.Arrow.triangle(5, 7, 0), fill: '#999' } },
      labelCfg: { autoRotate: true, style: { fill: '#888', fontSize: 9 } },
    }))

    const container = neo4jGraphContainer.value
    const width = container.clientWidth || 800
    const height = container.clientHeight || 600

    const layoutConfig = {
      force: { type: 'force', preventOverlap: true, linkDistance: 120, nodeStrength: -200, edgeStrength: 0.1 },
      circular: { type: 'circular', radius: 200 },
      grid: { type: 'grid' },
    }

    neo4jGraph = new G6.default.Graph({
      container,
      width,
      height,
      modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
      layout: layoutConfig[graphLayout.value] || layoutConfig.force,
      defaultNode: { type: 'circle', size: 24 },
      defaultEdge: { type: 'line' },
      fitView: true,
      fitViewPadding: 20,
    })

    neo4jGraph.data({ nodes: g6Nodes, edges: g6Edges })
    neo4jGraph.render()
  }).catch(() => {
    ElMessage.warning('G6 加载失败')
  })
}
</script>

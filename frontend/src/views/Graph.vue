<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>知识图谱可视化</h2>
      <div style="display: flex; align-items: center; gap: 12px;">
        <el-button @click="loadGraph" :loading="loading">刷新</el-button>
        <el-switch v-model="showLabels" active-text="标签" style="margin-left: 8px;" />
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="kg-stat-row" style="margin-bottom: 16px;">
      <div class="kg-stat-item">
        <div class="kg-stat-value">{{ stats.node_count || 0 }}</div>
        <div class="kg-stat-label">实体节点</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #409eff;">{{ stats.edge_count || 0 }}</div>
        <div class="kg-stat-label">关系边</div>
      </div>
    </div>

    <!-- 图谱画布 -->
    <div class="kg-card" style="padding: 0; overflow: hidden;">
      <div ref="graphContainer" style="width: 100%; height: 620px; background: #f5f7fa;"></div>
    </div>

    <!-- 节点详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="selectedNode?.label || '实体详情'" width="480px">
      <div v-if="selectedNode">
        <p><strong>名称:</strong> {{ selectedNode.label }}</p>
        <p><strong>类型:</strong> {{ selectedNode.group || '-' }}</p>
        <h4 style="margin-top: 16px;">关联关系:</h4>
        <div v-for="(r, i) in nodeRelations" :key="i" style="padding: 6px 0; border-bottom: 1px solid #eee;">
          <span v-if="r.source === selectedNode.id">
            --> <strong>{{ r.label }}</strong> --> {{ r.target }}
          </span>
          <span v-else>
            {{ r.source }} <-- <strong>{{ r.label }}</strong> --
          </span>
          <el-tag size="small" style="margin-left: 8px;">{{ (r.confidence || 0).toFixed(0) }}%</el-tag>
        </div>
        <div v-if="!nodeRelations.length" style="color: #999;">无关联关系</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { exportApi } from '../api'

const route = useRoute()
const projectId = route.params.id
const graphContainer = ref(null)
const loading = ref(false)
const showLabels = ref(true)
const stats = reactive({ node_count: 0, edge_count: 0 })
const detailVisible = ref(false)
const selectedNode = ref(null)
const nodeRelations = ref([])

let graph = null
let nodesData = []
let edgesData = []

const COLOR_PALETTE = [
  '#5B8FF9', '#61DDAA', '#F6BD16', '#E8684A', '#6DC8EC',
  '#9270CA', '#FF9D4D', '#269A99', '#FF99C3', '#5AD8A6',
]

async function loadGraph() {
  loading.value = true
  try {
    const data = await exportApi.graphData(projectId)
    nodesData = data.nodes || []
    edgesData = data.edges || []
    Object.assign(stats, data.stats || { node_count: nodesData.length, edge_count: edgesData.length })
    if (nodesData.length === 0) {
      ElMessage.info('暂无图谱数据，请先完成抽取与融合')
      return
    }
    await nextTick()
    renderGraph()
  } catch (e) {
    console.error('Graph load error:', e)
    ElMessage.error('加载图谱数据失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function renderGraph() {
  if (!graphContainer.value) return

  // 动态加载 G6（与 MultiGraph.vue 保持一致写法）
  import('@antv/g6').then((G6) => {
    if (graph) {
      graph.destroy()
      graph = null
    }

    const container = graphContainer.value
    if (!container || !nodesData.length) return

    // 分配颜色
    const groupColors = {}
    let ci = 0
    nodesData.forEach(n => {
      const g = n.group || '_default'
      if (!groupColors[g]) {
        groupColors[g] = COLOR_PALETTE[ci % COLOR_PALETTE.length]
        ci++
      }
      n.color = groupColors[g]
    })

    const width = container.clientWidth || 800
    const height = container.clientHeight || 620

    const g6Nodes = nodesData.map(n => ({
      id: n.id,
      label: (n.label || n.id).substring(0, 20),
      style: { fill: n.color, stroke: '#fff', lineWidth: 2 },
      labelCfg: { position: 'bottom', offset: 8, style: { fill: '#333', fontSize: 12 } },
      data: n,
    }))

    const g6Edges = edgesData.map((e, i) => ({
      id: `edge-${i}`,
      source: e.source,
      target: e.target,
      label: e.label || '',
      data: e,
      style: { stroke: '#bbb', lineWidth: 1.5, endArrow: { path: G6.default.Arrow.triangle(6, 8, 0), fill: '#999' } },
      labelCfg: { autoRotate: true, style: { fill: '#666', fontSize: 10 } },
    }))

    graph = new G6.default.Graph({
      container,
      width,
      height,
      modes: {
        default: ['drag-canvas', 'zoom-canvas', 'drag-node'],
      },
      layout: {
        type: 'force',
        preventOverlap: true,
        linkDistance: 180,
        nodeStrength: -300,
        edgeStrength: 0.1,
        collideStrength: 0.8,
        alpha: 1,
        alphaDecay: 0.028,
        alphaMin: 0.001,
      },
      defaultNode: {
        type: 'circle',
        size: 30,
      },
      defaultEdge: {
        type: 'line',
        style: { lineWidth: 1.5 },
      },
      fitView: true,
      fitViewPadding: 30,
      animate: true,
    })

    graph.data({ nodes: g6Nodes, edges: g6Edges })
    graph.render()

    graph.on('node:click', (evt) => {
      const node = evt.item
      const model = node.getModel()
      const nd = model.data || model
      selectedNode.value = nd
      nodeRelations.value = edgesData.filter(
        e => e.source === nd.id || e.target === nd.id
      )
      detailVisible.value = true
    })
  }).catch((err) => {
    console.error('G6 load error:', err)
    ElMessage.warning('G6 加载失败，请确认已安装 @antv/g6')
  })
}

watch(showLabels, (val) => {
  if (!graph) return
  const nodes = graph.getNodes()
  nodes.forEach(n => {
    const model = n.getModel()
    graph.updateItem(n, { labelCfg: { ...model.labelCfg, style: { ...model.labelCfg?.style, opacity: val ? 1 : 0 } } })
  })
})

onMounted(() => { loadGraph() })
onUnmounted(() => { if (graph) graph.destroy() })
</script>

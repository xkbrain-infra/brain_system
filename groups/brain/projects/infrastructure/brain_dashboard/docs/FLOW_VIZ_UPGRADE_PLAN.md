# Traffic Flow Visualization Upgrade Plan

## Overview

**Task**: Upgrade brain_dashboard proxy to display precise traffic flow between agents.
**Current State**: Only shows aggregate inbound/outbound statistics.
**Target State**: Show exact flow (source_agent → target_agent) with real-time topology.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  brain_gateway  │────▶│  Traffic Store   │────▶│ brain_dashboard │
│   (collector)   │     │   (time-series)  │     │   (visualizer)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                                               │
        │                                               │
        ▼                                               ▼
┌─────────────────┐                           ┌─────────────────┐
│   IPC Messages  │                           │  Flow Topology  │
│  (with routing) │                           │    Map UI       │
└─────────────────┘                           └─────────────────┘
```

## Upgrade Steps

### Phase 1: Data Collection Enhancement (brain_gateway)

**Files to modify**:
- `/xkagent_infra/brain/infrastructure/service/brain_gateway/src/collector.py`
- `/xkagent_infra/brain/infrastructure/service/brain_gateway/src/models.py`

**Changes**:
1. Add flow tracking to IPC message recording
2. Store source/target agent for each message
3. Add timestamp and latency tracking
4. Create time-series aggregation

**Data Structure**:
```python
class FlowRecord:
    timestamp: float
    source_agent: str
    target_agent: str
    message_type: str
    size_bytes: int
    latency_ms: float
    status: "success" | "error"
```

### Phase 2: Storage Layer (brain_dashboard)

**Files to create/modify**:
- `/src/core/flow_store.py` (new)
- `/src/core/storage.py` (extend)

**Features**:
1. Ring buffer for recent flows (last 10k messages)
2. Aggregation by time windows (1s, 1min, 5min)
3. Topology graph generation
4. Query API for flow patterns

### Phase 3: API Enhancement

**Files to modify**:
- `/src/api/v2/proxy.py`

**New Endpoints**:

```python
# GET /api/v2/proxy/flows
{
    "flows": [
        {"from": "agent-a", "to": "agent-b", "count": 150, "bps": 1024}
    ],
    "topology": {
        "nodes": [{"id": "agent-a", "type": "service"}],
        "edges": [{"from": "agent-a", "to": "agent-b", "weight": 150}]
    }
}

# GET /api/v2/proxy/flows/realtime (SSE)
Stream of flow updates every second

# GET /api/v2/proxy/flows/trace?agent=X
Show all flows in/out of specific agent
```

### Phase 4: Frontend Visualization

**Files to create**:
- `/web/components/FlowTopology.vue`
- `/web/components/FlowTable.vue`

**Features**:
1. D3.js force-directed graph for topology
2. Real-time updating flow table
3. Agent filtering and search
4. Time range selector

## Implementation Plan

| Step | Description | Files | Est. Time |
|------|-------------|-------|-----------|
| 1 | Update gateway collector | brain_gateway/src/collector.py | 2h |
| 2 | Create flow store | src/core/flow_store.py | 3h |
| 3 | Extend proxy API | src/api/v2/proxy.py | 2h |
| 4 | Add topology endpoint | src/api/v2/proxy.py | 2h |
| 5 | Frontend components | web/components/Flow*.vue | 4h |
| 6 | Integration tests | tests/test_flow_viz.py | 2h |

## Verification

1. Unit tests for flow store
2. Integration test with mock gateway
3. Load test (1000 msg/sec)
4. UI manual verification

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Gateway API change breaks existing | Medium | Version API, keep backward compat |
| Performance degradation | Low | Ring buffer limits memory use |
| Database size growth | Low | TTL on flow records (24h) |

## LEP Gates Compliance

- **G-GATE-NAWP**: Plan requires PMO approval before execution
- **G-GATE-ATOMIC**: Steps clearly defined per file
- **G-GATE-ROLLBACK-READY**: Keep v1.0 endpoints, add v2.0
- **G-GATE-VERIFICATION**: All tests must pass

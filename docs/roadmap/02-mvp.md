# MVP

## Goal
Publish a public dashboard with daily diffs.

## Deliverables
- Synthetic test runner for current modalities: AKS extension catalog, AKS Kubernetes versions, Azure Functions Flex, Container Apps provider metadata, and VM SKUs
- Static dashboard hosted by Azure Static Web Apps
- Public JSON endpoints under `/api`
- Daily static history and compact recent-change summaries
- Focused modality workflows that can merge fresh data into the live dashboard
- Methodology page explaining status semantics
- Blob storage or other durable external snapshot store remains future work

## Success Criteria
- Dashboard updates daily
- Users can see what changed today
- Builders can understand what `available`, `unavailable`, and `unknown` mean without Azure-expert context

# fincept-mcp-periphery (Project)

Date/timestamp-driven project board (local Linear-like).

## Quick open
- **Current status:** [STATUS.md](./STATUS.md)
- **Tool inventory:** [INVENTORY.md](./INVENTORY.md) (6 servers / 82 tools)
- **Roadmap:** [ROADMAP.md](./ROADMAP.md)
- **Today’s journal:** `journal/YYYY-MM-DD.md`
- **Issues:** `issues/ISSUE-<UTC>-<slug>.md`

## New work
1. `date -u +%Y%m%d-%H%M%S` → issue id prefix  
2. Create `issues/ISSUE-<that>-slug.md` with Spec + empty Timeline  
3. Set STATUS active issue  
4. Append Timeline rows as you work (UTC)  
5. Close issue → journal line + STATUS update  

## Naming
`ISSUE-20260719-160000-phase2-mcp-expand`  
= date `20260719` + time `160000` UTC + short slug  

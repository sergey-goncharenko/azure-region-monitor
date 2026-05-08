# Non-Functional Specification

## Performance
- Dashboard loads in <200ms globally
- API responds in <100ms

## Reliability
- Synthetic tests must be idempotent
- Dashboard must be static and globally cached

## Cost
- Target: < $50/month total

## Security
- No user data stored
- No authentication required for read-only API

## Maintainability
- Tests must be modular and easy to extend

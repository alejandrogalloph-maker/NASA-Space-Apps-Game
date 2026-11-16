# Code fixes

This revision includes the following corrections in `ui.py`:

1. Daily random directives are now selected only from the currently unlocked mission phase. Early missions no longer display actions that the game will reject as locked.
2. Failed building-worker reassignment now rolls back to the worker's previous building. A rejected move no longer leaves the worker unintentionally unassigned.
3. Bulk Sol advancement increments its reported count only after a Sol was successfully simulated. If the crew is already lost, the interface reports `Advanced 0 Sol(s)` rather than counting a failed attempt.
4. The web mission setup now uses the same 10-Sol minimum as the command-line mission setup.

## Verification

- All Python files compile successfully.
- Mission initialization and state serialization were checked across all four environments and crew sizes of 2, 6, and 10.
- Regression checks confirmed phase-locked actions are not offered, failed worker reassignment preserves the original assignment, and a failed Sol advance is not counted.

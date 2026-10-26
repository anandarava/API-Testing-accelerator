---
name: api-access-control-testing
description: How a senior API tester checks roles and permissions for one endpoint - who may call it, whose records, which data and fields.
---
## What is checked

Permissions are enforced by the API, not by the screens, so every rule is proven with real requests.
The checks match the OWASP API Security Top 10 access risks:

| Kind | What it proves | Example |
| --- | --- | --- |
| `allowed` | A role that may call the operation succeeds, and sees only the data it should | Receptionist checks in a CONFIRMED appointment → 200 |
| `denied` | Every role that must not call it is refused, and nothing changed | Patient checks in an appointment → 403; the appointment is still CONFIRMED |
| `ownership` | A role limited to its own records cannot reach another user's record of the same kind (second user) | Patient B opens patient A's lab result → 403 or 404 |
| `hidden_data` | Records or fields a role must not see are absent from responses and lists | A DRAFT lab result is not in the patient's list |
| `protected_field` | Fields a role must not change are refused or ignored | Doctor sends a new fee in their own profile update → 400, or 200 with the fee unchanged |

## Writing the cases

1. **One allowed case per allowed role**, in the role's normal scope, with `bodyChecks` that prove the
   result belongs to that role's scope.
2. **Denied roles share one case.** List every denied role in `roles`; the case runs once per role.
   Always add `verifyUnchanged`: read the record back as a role that may read it.
3. **Ownership needs two users of the same role.** The precondition creates the record as the first
   user; the case runs as the `second` user (`userSlot: "second"`). Also include the allowed case for
   the first user, so both sides are proven.
4. **Preconditions name the role that does them**, e.g. "As Patient (first user): book an
   appointment and keep its id as `{{created.appointmentId}}`". Use other operations from
   `operationIndex` to set data up.
5. **Status codes.** 401 means not logged in; 403 means logged in but not allowed; some APIs return
   404 to hide that a record exists. Use the status the contract documents for this operation. When
   the contract does not say which, choose the documented one and set `needsConfirmation` with a note.
6. **Credentials** come only through `request.auth` (`valid` for the case's role, `none`, `invalid`,
   `expired`). Never write usernames, passwords or tokens.
7. **System callers** (a payment gateway calling a webhook) are not user roles: when the operation is
   only for a system caller, every user role is denied.
8. **Only what the permission grid decides.** Roles in `unknown` are not tested; do not guess.

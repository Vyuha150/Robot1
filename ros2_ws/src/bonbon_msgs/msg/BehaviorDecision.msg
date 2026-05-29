# Final decision after safety validation
std_msgs/Header header
string event_id
builtin_interfaces/Time decided_at
string source_module
string person_id

string decision             # 'approved','rejected','modified','deferred','escalated'
string proposal_event_id    # links back to BehaviorProposal.event_id

string approved_action      # final action to execute
string approved_content
bool safety_approved

string rejection_reason     # if rejected
string modification_note    # if modified

float32 confidence
bool operator_alerted
bool logged

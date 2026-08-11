import { QueueStatus } from "../services/api";

export function TokenDisplay({ status }: { status: QueueStatus }) {
  return (
    <div className="token-card">
      <div className="token-code">{status.token.token_code}</div>
      <div className="token-dept">{status.department_name}</div>
      {status.token.priority === "urgent" ? (
        <div className="token-urgent">Priority — please proceed to staff now</div>
      ) : (
        <>
          <div className="token-wait">Estimated wait: ~{Math.round(status.token.estimated_wait_min)} min</div>
          <div className="token-ahead">{status.ahead_count} patient(s) ahead of you</div>
        </>
      )}
    </div>
  );
}

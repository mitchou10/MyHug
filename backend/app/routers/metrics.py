from fastapi import APIRouter

from app.auth.deps import CurrentUser
from app.metrics import METRICS, default_shown
from app.schemas.evaluation import MetricOut, TaskMetricsOut

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", summary="The metrics of every task: what an evaluation holds, in one place")
async def list_metrics(_: CurrentUser) -> list[TaskMetricsOut]:
    return [
        TaskMetricsOut(
            task=task,
            metrics=[MetricOut(id=m.id, name=m.name, higher=m.higher, primary=m.primary) for m in metrics],
            default_shown=default_shown(task),
        )
        for task, metrics in METRICS.items()
    ]

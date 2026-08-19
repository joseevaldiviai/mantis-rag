from fastapi import APIRouter, HTTPException

from ...core.db import SessionLocal
from ...core.log import log_event
from ...core.models import Machine, WorkOrder
from ...library.indexing import index_work_order, reindex_work_order
from ...schemas import WorkOrderCreate, WorkOrderResponse, WorkOrderUpdate, WorkOrderUpdateResponse

router = APIRouter(prefix="/work-orders", tags=["work-orders"])


def _to_response(wo: WorkOrder) -> WorkOrderResponse:
    return WorkOrderResponse(
        id=wo.id,
        machine_id=wo.machine_id,
        machine_name=wo.machine.name if wo.machine else None,
        title=wo.title,
        description=wo.description,
        priority=wo.priority,
        status=wo.status,
        assigned_to=wo.assigned_to,
        due_date=wo.due_date,
        metadata=wo.metadata_,
        created_at=wo.created_at,
    )


@router.post("", response_model=WorkOrderResponse, status_code=201)
def create_work_order(payload: WorkOrderCreate):
    """Registra una orden de trabajo y la indexa en FAISS (espacio work_orders)."""
    data = payload.model_dump()
    metadata = data.pop("metadata", None)

    with SessionLocal() as session:
        machine = session.get(Machine, payload.machine_id)
        if machine is None:
            raise HTTPException(
                status_code=404, detail=f"No existe la máquina {payload.machine_id}."
            )

        wo = WorkOrder(metadata_=metadata, **data)
        session.add(wo)
        session.flush()

        try:
            chunks = index_work_order(session, wo, machine.name)
        except Exception as exc:
            session.rollback()
            log_event(
                "error", "Fallo al indexar orden de trabajo",
                entity_type="work_order", entity_id=wo.id, exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error indexando la orden de trabajo: {exc}"
            ) from exc

        session.commit()
        log_event(
            "info", f"OT #{wo.id} registrada e indexada ({len(chunks)} chunk en FAISS)",
            entity_type="work_order", entity_id=wo.id,
        )
        return _to_response(wo)


@router.patch("/{work_order_id}", response_model=WorkOrderUpdateResponse)
def update_work_order(work_order_id: int, payload: WorkOrderUpdate):
    """Actualiza una OT. Si cambia el texto indexado (estado, prioridad…),
    borra los chunks viejos de FAISS y re-indexa automáticamente."""
    data = payload.model_dump(exclude_unset=True)

    with SessionLocal() as session:
        wo = session.get(WorkOrder, work_order_id)
        if wo is None:
            raise HTTPException(
                status_code=404, detail=f"No existe la orden de trabajo {work_order_id}."
            )

        # El nombre de la máquina entra en el texto indexado: hay que saber cuál
        # quedará tras el cambio (la relación puede estar desactualizada).
        machine_name = wo.machine.name if wo.machine else None
        if "machine_id" in data:
            new_machine = session.get(Machine, data["machine_id"])
            if new_machine is None:
                raise HTTPException(
                    status_code=404, detail=f"No existe la máquina {data['machine_id']}."
                )
            machine_name = new_machine.name

        if "metadata" in data:
            wo.metadata_ = data.pop("metadata")
        for field, value in data.items():
            setattr(wo, field, value)
        session.flush()

        try:
            chunks, reindexed = reindex_work_order(session, wo, machine_name)
        except Exception as exc:
            session.rollback()
            log_event(
                "error", "Fallo al re-indexar orden de trabajo",
                entity_type="work_order", entity_id=wo.id, exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error re-indexando la orden de trabajo: {exc}"
            ) from exc

        session.commit()
        log_event(
            "info",
            f"OT #{wo.id} actualizada: "
            + (f"re-indexada ({len(chunks)} chunk)" if reindexed else "sin cambios en el índice"),
            entity_type="work_order", entity_id=wo.id,
        )
        return WorkOrderUpdateResponse(
            work_order=_to_response(wo), reindexed=reindexed, num_chunks=len(chunks)
        )


@router.get("", response_model=list[WorkOrderResponse])
def list_work_orders():
    with SessionLocal() as session:
        orders = session.query(WorkOrder).order_by(WorkOrder.id).all()
        return [_to_response(wo) for wo in orders]

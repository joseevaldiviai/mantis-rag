from fastapi import APIRouter, HTTPException

from ..db import SessionLocal
from ..indexing import index_machine, reindex_machine
from ..log import log_event
from ..models import Machine
from ..schemas import MachineCreate, MachineResponse, MachineUpdate, MachineUpdateResponse

router = APIRouter(prefix="/machines", tags=["machines"])


def _to_response(machine: Machine) -> MachineResponse:
    return MachineResponse(
        id=machine.id,
        code=machine.code,
        name=machine.name,
        description=machine.description,
        location=machine.location,
        status=machine.status,
        metadata=machine.metadata_,
        created_at=machine.created_at,
    )


@router.post("", response_model=MachineResponse, status_code=201)
def create_machine(payload: MachineCreate):
    """Registra una maquinaria y la indexa automáticamente en FAISS (espacio machines)."""
    data = payload.model_dump()
    metadata = data.pop("metadata", None)

    with SessionLocal() as session:
        if session.query(Machine).filter(Machine.code == payload.code).first():
            raise HTTPException(
                status_code=409, detail=f"Ya existe una máquina con código {payload.code!r}."
            )

        machine = Machine(metadata_=metadata, **data)
        session.add(machine)
        session.flush()

        try:
            chunks = index_machine(session, machine)
        except Exception as exc:
            session.rollback()
            log_event(
                "error", "Fallo al indexar máquina",
                entity_type="machine", entity_id=machine.id, exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error indexando la máquina: {exc}"
            ) from exc

        session.commit()
        log_event(
            "info", f"Máquina {machine.name} registrada e indexada "
                    f"({len(chunks)} chunk en FAISS)",
            entity_type="machine", entity_id=machine.id,
        )
        return _to_response(machine)


@router.patch("/{machine_id}", response_model=MachineUpdateResponse)
def update_machine(machine_id: int, payload: MachineUpdate):
    """Actualiza una máquina. Si cambia el texto indexado (estado, descripción…),
    borra los chunks viejos de FAISS y re-indexa automáticamente."""
    data = payload.model_dump(exclude_unset=True)

    with SessionLocal() as session:
        machine = session.get(Machine, machine_id)
        if machine is None:
            raise HTTPException(status_code=404, detail=f"No existe la máquina {machine_id}.")

        if "code" in data:
            existing = (
                session.query(Machine)
                .filter(Machine.code == data["code"], Machine.id != machine_id)
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=409, detail=f"Ya existe una máquina con código {data['code']!r}."
                )

        if "metadata" in data:
            machine.metadata_ = data.pop("metadata")
        for field, value in data.items():
            setattr(machine, field, value)
        session.flush()

        try:
            chunks, reindexed = reindex_machine(session, machine)
        except Exception as exc:
            session.rollback()
            log_event(
                "error", "Fallo al re-indexar máquina",
                entity_type="machine", entity_id=machine.id, exc=exc,
            )
            raise HTTPException(
                status_code=500, detail=f"Error re-indexando la máquina: {exc}"
            ) from exc

        session.commit()
        log_event(
            "info",
            f"Máquina {machine.name} actualizada: "
            + (f"re-indexada ({len(chunks)} chunk)" if reindexed else "sin cambios en el índice"),
            entity_type="machine", entity_id=machine.id,
        )
        return MachineUpdateResponse(
            machine=_to_response(machine), reindexed=reindexed, num_chunks=len(chunks)
        )


@router.get("", response_model=list[MachineResponse])
def list_machines():
    with SessionLocal() as session:
        machines = session.query(Machine).order_by(Machine.id).all()
        return [_to_response(m) for m in machines]

"""Pushes one already-stocked-in scrap record to SAP via the ICF ZAI_DIM endpoint
(sap_client.post_remnant), logging the attempt locally either way for SE16
reconciliation against ZAI_DIM_LOG (sap_sync_log). Since the 2026-07-29 SAP-side
rewrite, a successful call already means SAP has done the MIGO 531 stock receipt
and Z_SCRAP_CLASSIFY batch classification itself -- the batch number and bin
zone it returns are the caller's confirmation of where the remnant physically is.
"""

import sap_client
import sap_sync_log


def export_to_sap(record: dict, matnr, *, board_length_cm, board_width_cm, product_area_cm2,
                   scrap_area_cm2,
                   plant="2604", sloc="100B", quantity=1, zone=None,
                   scrap_length_cm=None, scrap_width_cm=None,
                   candidate_options=None, binding_status="UNBOUND"):
    """`record` is a row dict as returned by excel_db.append_record/get_record.

    matnr is required and must be supplied by the caller -- this software has no
    source of truth mapping a scrap record to an SAP material number (材質/A/B
    fit counts do not determine it), so it is never inferred or defaulted here.
    board_length_cm/board_width_cm/product_area_cm2/scrap_area_cm2 likewise come
    from the caller's own design-measurement result, never recomputed here.
    scrap_area_cm2 is the remnant's own precisely-computed area (not the
    product's), and is what actually goes into SAP's precomputed_area field --
    see sap_client.post_remnant.

    charg is no longer accepted -- the batch is assigned by SAP's own MIGO 531
    call and comes back in the result, it is never sent.
    """
    scrap_id = record.get("餘料編號")

    result = sap_client.post_remnant(
        matnr=matnr,
        board_length_cm=board_length_cm, board_width_cm=board_width_cm,
        product_area_cm2=product_area_cm2, scrap_area_cm2=scrap_area_cm2,
        plant=plant, sloc=sloc, quantity=quantity, zone=zone,
        scrap_length_cm=scrap_length_cm, scrap_width_cm=scrap_width_cm,
        source_id=scrap_id, candidate_options=candidate_options,
        binding_status=binding_status,
    )

    sap_sync_log.append_sync_record(
        scrap_id=scrap_id, source_id=scrap_id, matnr=matnr,
        board_length_cm=board_length_cm, board_width_cm=board_width_cm,
        product_area_cm2=product_area_cm2,
        result=result,
    )
    return result


def match_orders(record: dict) -> list:
    """Intended contract: given a scrap record, query SAP (or a synced local
    copy of open orders) for orders whose standard-product/quantity needs this
    scrap could satisfy, ranked by fit. Not implemented -- out of scope for this
    phase (see project spec's MIGO/CT04 roadmap note)."""
    return []

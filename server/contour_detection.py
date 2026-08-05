"""Classical-CV auto contour detection for photos taken under uncontrolled,
real production-floor conditions (not a clean/controlled background).

Known accuracy limitations for this POC (documented, not solved here):
- Shadows / uneven lighting can distort the adaptive-threshold contour.
- Cluttered backgrounds (other scrap, machinery, floor markings) can produce
  multiple similar-sized contours, and the largest-contour heuristic may grab
  the wrong object.
- Glossy/reflective surfaces can fragment the contour via highlight edges.
- Oblique (non top-down) camera angles break the accuracy of the existing
  2-point calibration across the frame; operators should shoot top-down.
- The confidence score below is a crude heuristic, not a validated metric.
  surface-calculate.html has no manual-trace fallback -- a successful
  detection is used automatically (low-confidence results still proceed, just
  with a warning surfaced to the operator); a failed detection requires
  re-uploading a clearer photo.

Approach: try two classical thresholding candidates (adaptive Gaussian, which
tolerates uneven lighting, and global Otsu) and pick whichever yields a better
largest-contour by a quality heuristic (solidity, border-touching, area ratio,
ambiguity vs. the second-largest contour).
"""

import cv2
import numpy as np

import config


def _quality_score(contour, img_h, img_w, ambiguity_penalty):
    area = cv2.contourArea(contour)
    if area <= 0:
        return 0.0

    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    solidity = (area / hull_area) if hull_area > 0 else 0.0

    x, y, w, h = cv2.boundingRect(contour)
    margin = 2
    touches = 0
    if x <= margin:
        touches += 1
    if y <= margin:
        touches += 1
    if x + w >= img_w - margin:
        touches += 1
    if y + h >= img_h - margin:
        touches += 1
    border_penalty = 1.0 if touches >= 3 else (0.5 if touches == 2 else 0.0)

    area_ratio = area / (img_w * img_h)
    area_ratio_penalty = 1.0 if area_ratio > 0.9 else 0.0

    score = solidity - 0.4 * border_penalty - 0.3 * area_ratio_penalty - ambiguity_penalty
    return max(0.0, min(1.0, score))


def _find_best_contour(mask, min_area, max_area):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contours_sorted = sorted(contours, key=cv2.contourArea, reverse=True)
    largest = contours_sorted[0]
    largest_area = cv2.contourArea(largest)
    if largest_area < min_area or largest_area > max_area:
        # Too small = noise; too large (near the full frame) almost always means
        # thresholding caught the whole image (e.g. a blank/featureless photo)
        # rather than an actual object, so treat it as "nothing detected" too.
        return None
    ambiguity_penalty = 0.0
    if len(contours_sorted) > 1:
        second_area = cv2.contourArea(contours_sorted[1])
        largest_area = cv2.contourArea(largest)
        if largest_area > 0 and (second_area / largest_area) > 0.7:
            ambiguity_penalty = 0.2
    return largest, ambiguity_penalty


def detect_contour(image_bytes, display_width, display_height):
    """Returns a dict with contour points already scaled into the frontend's
    canvas coordinate space (display_width x display_height), so the existing
    calibration/shoelace math in surface-calculate.html needs no changes."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "warning": "無法解析圖片檔案，請確認檔案格式。"}

    orig_h, orig_w = img.shape[:2]
    scale = min(1.0, config.CONTOUR_MAX_WORKING_DIMENSION_PX / float(max(orig_h, orig_w)))
    work = cv2.resize(img, (max(1, int(orig_w * scale)), max(1, int(orig_h * scale)))) if scale < 1.0 else img
    work_h, work_w = work.shape[:2]

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    min_area = config.CONTOUR_MIN_AREA_RATIO * work_w * work_h
    max_area = 0.95 * work_w * work_h

    candidate_masks = {
        "adaptive": cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 5
        ),
        "otsu": cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
    }

    best = None
    for method, mask in candidate_masks.items():
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
        found = _find_best_contour(cleaned, min_area, max_area)
        if found is None:
            continue
        contour, ambiguity_penalty = found
        score = _quality_score(contour, work_h, work_w, ambiguity_penalty)
        if best is None or score > best["score"]:
            best = {"method": method, "contour": contour, "score": score}

    if best is None:
        return {"ok": False, "warning": "偵測不到明顯的輪廓，請改善光線或背景後重新拍攝上傳。"}

    perimeter = cv2.arcLength(best["contour"], True)
    approx = cv2.approxPolyDP(best["contour"], 0.01 * perimeter, True)
    points_work = approx.reshape(-1, 2).astype(float)
    if len(points_work) < 3:
        return {"ok": False, "warning": "偵測到的輪廓過於簡單，請重新拍攝上傳。"}

    points_orig = points_work / scale if scale < 1.0 else points_work
    display_scale_x = display_width / orig_w if orig_w else 1.0
    display_scale_y = display_height / orig_h if orig_h else 1.0
    contour_px = [
        {"x": float(x * display_scale_x), "y": float(y * display_scale_y)}
        for x, y in points_orig
    ]

    confidence = round(best["score"], 3)
    warning = None
    if confidence < config.CONTOUR_DETECTION_CONFIDENCE_THRESHOLD:
        warning = "自動偵測信心較低，建議確認結果或重新拍攝上傳。"

    return {
        "ok": True,
        "contour_px": contour_px,
        "confidence": confidence,
        "method": best["method"],
        "original_width": orig_w,
        "original_height": orig_h,
        "warning": warning,
    }

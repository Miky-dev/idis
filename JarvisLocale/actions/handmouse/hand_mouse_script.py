"""
Script standalone (Python 3.12) per HandMouse.
Gira in un processo separato per evitare conflitti con Python 3.13.
"""

import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import math
import time
from collections import deque

pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0
SCREEN_W, SCREEN_H = pyautogui.size()
SENSITIVITY       = 1.5
SMOOTHING_FRAMES  = 5
CLICK_THRESHOLD   = 0.04
CLICK_COOLDOWN    = 0.6
SCROLL_SPEED      = 30
CAMERA_INDEX      = 0
FRAME_W, FRAME_H  = 640, 480

def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)

def finger_up(lm, tip, pip):
    return lm[tip].y < lm[pip].y

def map_range(val, in_min, in_max, out_min, out_max):
    val = max(in_min, min(in_max, val))
    return (val - in_min) / (in_max - in_min) * (out_max - out_min) + out_min

def detect_gesture(lm):
    index_up  = finger_up(lm, 8,  6)
    middle_up = finger_up(lm, 12, 10)
    ring_up   = finger_up(lm, 16, 14)
    pinky_up  = finger_up(lm, 20, 18)
    pinch_dist = dist(lm[4], lm[8])
    if pinch_dist < CLICK_THRESHOLD and index_up:
        return 'click'
    if index_up and middle_up and ring_up and pinky_up:
        return 'scroll'
    if index_up and middle_up and not ring_up and not pinky_up:
        return 'rightclick'
    if not index_up and not middle_up and not ring_up and not pinky_up:
        return 'drag'
    if index_up and not middle_up and not ring_up and not pinky_up:
        return 'move'
    return 'idle'

COLORS = {
    'move':(0,255,136),'click':(0,200,255),
    'rightclick':(255,100,50),'scroll':(255,220,0),
    'drag':(200,50,255),'idle':(120,120,140),
}
GESTURE_LABELS = {
    'move':'Solo indice - Muovi','click':'Pinch - Click SX',
    'rightclick':'Indice+Medio - Click DX','scroll':'Mano aperta - Scroll',
    'drag':'Pugno - Drag','idle':'In attesa',
}

def draw_skeleton(frame, lm_list, gesture):
    h, w = frame.shape[:2]
    color = COLORS.get(gesture, (120,120,140))
    for conn in mp.solutions.hands.HAND_CONNECTIONS:
        a, b = conn
        xa,ya = int(lm_list[a].x*w), int(lm_list[a].y*h)
        xb,yb = int(lm_list[b].x*w), int(lm_list[b].y*h)
        cv2.line(frame,(xa,ya),(xb,yb),color,2,cv2.LINE_AA)
    for i,lm in enumerate(lm_list):
        x,y = int(lm.x*w), int(lm.y*h)
        r = 7 if i in (4,8) else 4
        cv2.circle(frame,(x,y),r,color,-1,cv2.LINE_AA)
        cv2.circle(frame,(x,y),r+2,(255,255,255),1,cv2.LINE_AA)

def draw_ui(frame, gesture, cursor_pos, fps, click_ready):
    h, w = frame.shape[:2]
    color = COLORS.get(gesture,(120,120,140))
    overlay = frame.copy()
    cv2.rectangle(overlay,(0,0),(w,50),(10,10,20),-1)
    cv2.addWeighted(overlay,0.75,frame,0.25,0,frame)
    label = GESTURE_LABELS.get(gesture, gesture)
    cv2.putText(frame,label,(14,32),cv2.FONT_HERSHEY_SIMPLEX,0.7,color,2,cv2.LINE_AA)
    cv2.putText(frame,f'FPS:{fps:.0f}',(w-90,32),cv2.FONT_HERSHEY_SIMPLEX,0.6,(180,180,200),1,cv2.LINE_AA)
    cx = max(8,min(w-8,int(cursor_pos[0]/SCREEN_W*w)))
    cy = max(8,min(h-8,int(cursor_pos[1]/SCREEN_H*h)))
    cv2.circle(frame,(cx,cy),10,(0,200,255) if gesture=='click' else color,-1,cv2.LINE_AA)
    cv2.circle(frame,(cx,cy),10,(255,255,255),1,cv2.LINE_AA)
    st = 'CLICK PRONTO' if click_ready else 'COOLDOWN'
    sc = (0,255,136) if click_ready else (80,80,120)
    cv2.putText(frame,st,(14,h-14),cv2.FONT_HERSHEY_SIMPLEX,0.5,sc,1,cv2.LINE_AA)
    global SENSITIVITY
    cv2.putText(frame,f'S={SENSITIVITY:.1f}  +/-=sensibilita  Q=disattiva',
                (14,h-30),cv2.FONT_HERSHEY_SIMPLEX,0.42,(80,80,100),1,cv2.LINE_AA)

def main():
    global SENSITIVITY
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(max_num_hands=1, model_complexity=1,
                           min_detection_confidence=0.7, min_tracking_confidence=0.5)
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    if not cap.isOpened():
        print("⚠️ HandMouse: webcam non disponibile.")
        return

    history_x  = deque(maxlen=SMOOTHING_FRAMES)
    history_y  = deque(maxlen=SMOOTHING_FRAMES)
    cursor_x   = SCREEN_W // 2
    cursor_y   = SCREEN_H // 2
    last_click = 0
    is_dragging = False
    scroll_ref_y = None
    prev_time  = time.time()

    print("✋ HandMouse attivo — Q nella finestra per disattivare.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res   = hands.process(rgb)
        now   = time.time()
        fps   = 1.0 / max(now - prev_time, 1e-6)
        prev_time = now
        click_ready = (now - last_click) > CLICK_COOLDOWN

        if res.multi_hand_landmarks:
            lm      = res.multi_hand_landmarks[0].landmark
            gesture = detect_gesture(lm)
            raw_x, raw_y = lm[8].x, lm[8].y
            mapped_x = map_range(raw_x, 0.1, 0.9, 0, SCREEN_W)
            mapped_y = map_range(raw_y, 0.1, 0.9, 0, SCREEN_H)
            history_x.append(mapped_x); history_y.append(mapped_y)
            sx = int(np.mean(history_x)); sy = int(np.mean(history_y))

            if gesture == 'move':
                cursor_x, cursor_y = sx, sy
                pyautogui.moveTo(cursor_x, cursor_y)
                scroll_ref_y = None
                if is_dragging: pyautogui.mouseUp(); is_dragging = False
            elif gesture == 'click':
                cursor_x, cursor_y = sx, sy
                pyautogui.moveTo(cursor_x, cursor_y)
                if click_ready: pyautogui.click(); last_click = now
            elif gesture == 'rightclick':
                cursor_x, cursor_y = sx, sy
                pyautogui.moveTo(cursor_x, cursor_y)
                if click_ready: pyautogui.rightClick(); last_click = now
            elif gesture == 'scroll':
                wy = lm[0].y
                if scroll_ref_y is None: scroll_ref_y = wy
                else:
                    delta = wy - scroll_ref_y; scroll_ref_y = wy
                    amt = int(-delta * SCROLL_SPEED * 10)
                    if abs(amt) > 1: pyautogui.scroll(amt)
                if is_dragging: pyautogui.mouseUp(); is_dragging = False
            elif gesture == 'drag':
                dx = int(map_range(lm[0].x, 0.1, 0.9, 0, SCREEN_W))
                dy = int(map_range(lm[0].y, 0.1, 0.9, 0, SCREEN_H))
                pyautogui.moveTo(dx, dy); cursor_x, cursor_y = dx, dy
                if not is_dragging: pyautogui.mouseDown(); is_dragging = True
                scroll_ref_y = None
            else:
                scroll_ref_y = None
                if is_dragging: pyautogui.mouseUp(); is_dragging = False

            draw_skeleton(frame, lm, gesture)
            draw_ui(frame, gesture, (cursor_x, cursor_y), fps, click_ready)
        else:
            draw_ui(frame, 'idle', (cursor_x, cursor_y), fps, True)
            if is_dragging: pyautogui.mouseUp(); is_dragging = False
            scroll_ref_y = None

        cv2.imshow('IDIS — HandMouse  [Q = disattiva]', frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key in (ord('+'), ord('=')):
            SENSITIVITY = min(4.0, SENSITIVITY + 0.1)
        elif key == ord('-'):
            SENSITIVITY = max(0.5, SENSITIVITY - 0.1)

    if is_dragging: pyautogui.mouseUp()
    cap.release()
    cv2.destroyAllWindows()
    print("✋ HandMouse disattivato.")

if __name__ == "__main__":
    main()

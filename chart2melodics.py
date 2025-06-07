# ==== CONFIGURATION ====
#INPUT_FILE = 'rainbow-moon.mid'
#OUTPUT_FILE = 'rainbow-melodics.mid'
INPUT_FILE = 'moon.mid'
OUTPUT_FILE = 'melodics.mid'
EXPECTED_TPB = 96 # Mandatory for the Melodics
DEFAULT_DURATION = 8  # Default note duration for synthetic note_off

from mido import MidiFile, MidiTrack, Message, MetaMessage
from collections import defaultdict

# ---------- STEP 1: Read MIDI to flat events list without note_off ----------
def read_midi_events(input_path):
    mid = MidiFile(input_path)
    if mid.ticks_per_beat != EXPECTED_TPB:
        raise ValueError(f"ticks_per_beat is {mid.ticks_per_beat}, expected {EXPECTED_TPB}")

    events_by_tick = defaultdict(list)

    for track_index, track in enumerate(mid.tracks):
        abs_time = 0
        for msg in track:
            abs_time += msg.time

            if msg.type == 'note_off':
                continue  # Skip note_off

            events_by_tick[abs_time].append({
                "tick": abs_time,
                "track": track_index,
                "msg": msg
            })

    return events_by_tick


# ---------- STEP 2: Transform events ----------
def replace_composite_notes(events_by_tick, match_notes, replace_with):
    """
    Replaces multiple specific notes played simultaneously with a single note.
    Only applies when all match_notes are present in a tick.
    """
    for tick, events in list(events_by_tick.items()):
        note_ons = [e for e in events if e["msg"].type == 'note_on']
        other_events = [e for e in events if e["msg"].type != 'note_on']

        found_indices = []
        for i, e in enumerate(note_ons):
            if e["msg"].note in match_notes:
                found_indices.append(i)

        if len(found_indices) == len(match_notes):
            base_event = min(
                    (note_ons[i] for i in found_indices),
                    key=lambda e: e["msg"].note
                )
            new_msg = base_event["msg"].copy(note=replace_with)
            new_event = {**base_event, "msg": new_msg}

            # Keep all other note_ons not used in replacement
            remaining_note_ons = [
                e for i, e in enumerate(note_ons)
                if i not in found_indices
            ]

            # Replace events
            events_by_tick[tick] = remaining_note_ons + [new_event] + other_events
    return events_by_tick

def replace_single_note(events_by_tick, from_note, to_note):
    """
    Replaces all instances of a specific note with another note.
    """
    for tick, events in events_by_tick.items():
        for i, event in enumerate(events):
            if event["msg"].type == 'note_on' and event["msg"].note == from_note:
                new_msg = event["msg"].copy(note=to_note)
                events[i] = {**event, "msg": new_msg}
    return events_by_tick

def assign_hands_for_note(events_by_tick, notes, left_track, right_track):
    ticks_per_beat = EXPECTED_TPB
    TICKS_1_4 = ticks_per_beat       # 96
    TICKS_1_8 = ticks_per_beat // 2  # 48
    TICKS_1_16 = ticks_per_beat // 4 # 24

    note_hits = []

    # Collect all note_on events for the given note
    for tick in sorted(events_by_tick.keys()):
        for event in events_by_tick[tick]:
            msg = event["msg"]
            if msg.type == "note_on" and msg.note in notes:
                note_hits.append({
                    "tick": tick,
                    "event": event
                })

    # Determine which hand played the note
    for i, hit in enumerate(note_hits):
        tick = hit["tick"]
        event = hit["event"]

        # Determine the strong beat: 1/4 or 1/8
        subdivision = tick % ticks_per_beat
        is_strong = subdivision == 0 or subdivision == TICKS_1_8
        is_weak_next = False

        hand_track = left_track  # default to left hand

        if is_strong and i + 1 < len(note_hits):
            next_tick = note_hits[i + 1]["tick"]
            if next_tick - tick == TICKS_1_16:
                hand_track = right_track  # right hand
                is_weak_next = True

        # Update the event's track
        if (is_strong and is_weak_next) or not is_strong:
            event["track"] = hand_track

    return events_by_tick

def replace_track(events_by_tick, from_track, to_track):
    for tick_events in events_by_tick.values():
        for event in tick_events:
            if event.get("track") == from_track:
                event["track"] = to_track
    return events_by_tick

def replace_note_track(events_by_tick, notes, to_track):
    for tick_events in events_by_tick.values():
        for event in tick_events:
            msg = event["msg"]
            if msg.type == "note_on" and msg.note in notes:
                event["track"] = to_track
    return events_by_tick

def replace_note_if_velocity(events_by_tick, from_note, from_vel, to_note):
    """
    Replace note from_note with note to_note if its velocity is exactly from_vel.
    New velocity is always set to 100.
    """
    for tick, events in events_by_tick.items():
        for event in events:
            msg = event["msg"]
            if msg.type == "note_on" and msg.note == from_note and msg.velocity == from_vel:
                new_msg = msg.copy(note=to_note, velocity=100)
                event["msg"] = new_msg
    return events_by_tick
    
def detect_flam(events_by_tick, from_note, from_vel, to_note, left_track, right_track):
    """
    Detect a flam pattern: if a note_on matches (from_note, from_vel),
    replace it with to_note at right_track, and insert a duplicate at left_track,
    both with velocity 100 in the same tick.
    """
    for tick, events in events_by_tick.items():
        new_events = []
        
        for event in events:
            msg = event["msg"]
            if msg.type == "note_on" and msg.note == from_note and msg.velocity == from_vel:
                 # Create right-hand note (replacing original)
                new_right_msg = msg.copy(note=to_note, velocity=100)
                event["msg"] = new_right_msg
                event["track"] = right_track

                # Create left-hand flam note
                left_msg = msg.copy(note=to_note, velocity=100)
                left_event = {"msg": left_msg, "track": left_track, "tick": tick}

                new_events.append(left_event)
                
        if new_events:
            events_by_tick[tick].extend(new_events)
        
    return events_by_tick

def replace_velocity_if_velocity(events_by_tick, from_vel, to_vel):
    """
    Replace notes velocity with velocity to_vel if its velocity is exactly from_vel.
    """
    for tick, events in events_by_tick.items():
        for event in events:
            msg = event["msg"]
            if msg.type == "note_on" and msg.velocity == from_vel:
                new_msg = msg.copy(velocity=to_vel)
                event["msg"] = new_msg
    return events_by_tick


# ---------- STEP 3: Write MIDI from flat events list with note_off generation ----------
def write_midi(events_by_tick, output_path, in_track):
    new_mid = MidiFile()
    new_mid.ticks_per_beat = EXPECTED_TPB

    # Group events by track
    track_events = defaultdict(list)
    for tick in sorted(events_by_tick.keys()):
        for event in events_by_tick[tick]:
            track_events[event["track"]].append(event)

    for track_index in sorted(track_events.keys()):
        if in_track >= 0 and track_index != in_track:
            continue
        new_track = MidiTrack()
        new_mid.tracks.append(new_track)

        # Create flat list of (tick, msg)
        flat_events = []

        for event in track_events[track_index]:
            tick = event["tick"]
            msg = event["msg"]
            flat_events.append((tick, msg))

            if msg.type == 'note_on':
                # Add synthetic note_off at tick + DEFAULT_DURATION
                off_tick = tick + DEFAULT_DURATION
                note_off = Message('note_off', note=msg.note, velocity=0, channel=msg.channel)
                flat_events.append((off_tick, note_off))

        # Sort by absolute time
        flat_events.sort(key=lambda e: e[0])

        # Write with correct delta times
        last_tick = 0
        for tick, msg in flat_events:
            delta = tick - last_tick
            last_tick = tick
            new_track.append(msg.copy(time=delta))

    new_mid.tracks[0].name = 'RH'
    new_mid.tracks[1].name = 'LH'

    new_mid.save(output_path)
    print(f"[OK] Saved to {output_path}")


# ---------- MAIN ----------
def main():
    print("[INFO] Reading MIDI...")
    events = read_midi_events(INPUT_FILE)

    print("[INFO] Transforming events...")
    events = replace_composite_notes(events, {110, 98}, 48)     # HighTom
    events = replace_composite_notes(events, {111, 99}, 45)     # MidTom
    events = replace_composite_notes(events, {112, 100}, 43)    # LowTom

    events = replace_single_note(events, 96, 36)   # Kick
    events = replace_single_note(events, 95, 36)   # Kick [Kickx2 in Chart (Moonscraper)]
    events = replace_single_note(events, 97, 38)   # Snare
    events = replace_single_note(events, 98, 42)   # ClosedHiHat
    events = replace_single_note(events, 99, 51)   # Ride
    events = replace_single_note(events, 100, 49)  # Crash

    events = replace_note_if_velocity(events, 49, 127, 44) # PedalHiHat
    events = replace_note_if_velocity(events, 42, 127, 46) # OpenHiHat
    events = replace_velocity_if_velocity(events, 1, 20)

    # track 5 - left hand, track 6 - right hand
    events = replace_note_track(events, [38], 5)
    events = assign_hands_for_note(events, [38, 42], 5, 6)
    events = assign_hands_for_note(events, [38, 48, 45, 43], 5, 6)
    events = detect_flam(events, 38, 127, 38, 5, 6)

    # now track 2 - right hand
    events = replace_track(events, 0, 2)
    events = replace_track(events, 1, 2)
    events = replace_track(events, 6, 2)

    print("[INFO] Writing MIDI with generated note_off...")
    write_midi(events, OUTPUT_FILE, -1)


if __name__ == "__main__":
    main()

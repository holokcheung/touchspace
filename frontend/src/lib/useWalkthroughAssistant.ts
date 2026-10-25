import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AskContext, AskResult, FloorMap } from "../api/types";
import { playCue } from "./cues";
import { dist } from "./geometry";
import {
  buildScene,
  describeSurroundings,
  hasMapData,
  type Pose,
} from "./soundscape";
import { createListener, speak, stopSpeaking, type Listener } from "./voice";

export type VoicePhase =
  "idle" | "starting" | "listening" | "thinking" | "speaking";
export function useWalkthroughAssistant(
  map: FloorMap,
  pose: Pose | null,
  speakAnswers: boolean,
  online: boolean,
  avoidStairs: boolean,
) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const phaseRef = useRef<VoicePhase>("idle");
  const poseRef = useRef(pose);
  poseRef.current = pose;
  const options = useRef({ speakAnswers, avoidStairs });
  options.current = { speakAnswers, avoidStairs };
  const listener = useRef<Listener | null>(null);
  const held = useRef(false);
  const alive = useRef(true);
  const generation = useRef(0);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const context = useRef<AskContext>({
    last_place_id: null,
    current_place_id: null,
    avoid_stairs: false,
  });
  const changePhase = useCallback((next: VoicePhase) => {
    phaseRef.current = next;
    if (alive.current) setPhase(next);
  }, []);
  const clearTimer = () => {
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = null;
  };
  const fail = useCallback(
    (message: string) => {
      if (!alive.current) return;
      generation.current++;
      held.current = false;
      clearTimer();
      listener.current?.cancel();
      listener.current = null;
      setError(message);
      changePhase("idle");
      playCue("error");
    },
    [changePhase],
  );

  const ask = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      const currentPose = poseRef.current;
      if (
        !text ||
        !currentPose ||
        !alive.current ||
        phaseRef.current === "thinking"
      )
        return;
      const id = ++generation.current;
      clearTimer();
      held.current = false;
      listener.current?.cancel();
      listener.current = null;
      stopSpeaking();
      setQuestion(text);
      setAnswer("");
      setError("");
      changePhase("thinking");
      try {
        let response: string;
        if (
          /^(where am i|what(?:'s| is) (?:around|near|ahead of) me|describe (?:my surroundings|this room)|what is ahead)[?.!]*$/i.test(
            text,
          )
        ) {
          response = describeSurroundings(buildScene(map), currentPose);
          setResult(null);
        } else if (!online) {
          response =
            describeSurroundings(buildScene(map), currentPose) +
            " In this offline version I can describe your surroundings. Open the connected app to ask about other places and routes.";
        } else {
          const scene = buildScene(map);
          if (!hasMapData(scene, currentPose.position)) {
            response =
              "You're outside the mapped area. Return to the map before asking for directions. " +
              describeSurroundings(scene, currentPose);
            setResult(null);
          } else {
            const nearest = [...map.landmarks].sort(
              (a, b) =>
                dist(a.position, currentPose.position) -
                dist(b.position, currentPose.position),
            )[0];
            const data = await api.ask(map.id, text, {
              ...context.current,
              current_place_id: nearest?.id ?? null,
              avoid_stairs: options.current.avoidStairs,
            });
            if (!alive.current || id !== generation.current) return;
            context.current = data.context;
            setResult(data);
            response = data.answer;
            if (data.route?.found)
              response = `Recorded route starts at ${data.route.origin_name}. ${response}`;
          }
        }
        if (!alive.current || id !== generation.current) return;
        setAnswer(response);
        if (options.current.speakAnswers) {
          changePhase("speaking");
          const speech = await speak(response);
          await speech.done;
        }
        if (alive.current && id === generation.current) changePhase("idle");
      } catch (e) {
        if (id === generation.current)
          fail(e instanceof Error ? e.message : "Could not answer. Try again.");
      }
    },
    [map, online, changePhase, fail],
  );

  const release = useCallback(() => {
    if (!held.current) return;
    held.current = false;
    // start() will see the release if permission or SDK setup is still pending.
    if (phaseRef.current === "listening") {
      changePhase("thinking");
      playCue("listen-stop");
      timeout.current = setTimeout(
        () => fail("No speech received. Try again or type your question."),
        15000,
      );
      void listener.current
        ?.stop()
        .catch(() => fail("Could not finish recording. Please try again."));
    }
  }, [changePhase, fail]);

  const press = useCallback(async () => {
    if (
      held.current ||
      ["starting", "listening", "thinking"].includes(phaseRef.current)
    )
      return;
    const captureId = ++generation.current;
    stopSpeaking();
    held.current = true;
    setError("");
    changePhase("starting");
    try {
      const input = await createListener({
        onResult: (text) => {
          if (!alive.current || captureId !== generation.current) return;
          changePhase("idle");
          void ask(text);
        },
        onError: (message) => {
          if (captureId === generation.current) fail(message);
        },
        onStateChange: (listening) => {
          if (!alive.current || captureId !== generation.current) return;
          if (listening) {
            changePhase("listening");
            playCue("listen-start");
          } else if (phaseRef.current === "listening") {
            held.current = false;
            changePhase("thinking");
            clearTimer();
            timeout.current = setTimeout(
              () =>
                fail("No speech received. Try again or type your question."),
              15000,
            );
          }
        },
      });
      if (!alive.current || captureId !== generation.current) {
        input.cancel();
        return;
      }
      listener.current = input;
      if (!held.current) {
        input.cancel();
        changePhase("idle");
        return;
      }
      await input.start();
      if (!alive.current || captureId !== generation.current) {
        input.cancel();
        return;
      }
      if (phaseRef.current !== "listening") return;
      if (!held.current) {
        held.current = true;
        release();
      } else {
        clearTimer();
        timeout.current = setTimeout(release, 60000);
      }
    } catch {
      fail(
        "Could not start the microphone. You can type your question instead.",
      );
    }
  }, [ask, changePhase, fail, release]);

  const stop = useCallback(() => {
    generation.current++;
    held.current = false;
    clearTimer();
    listener.current?.cancel();
    listener.current = null;
    stopSpeaking();
    changePhase("idle");
  }, [changePhase]);
  useEffect(() => {
    alive.current = true;
    const blur = () => {
      if (["listening", "starting"].includes(phaseRef.current)) stop();
    };
    const hidden = () => {
      if (document.hidden) stop();
    };
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      stop();
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [stop]);
  return {
    phase,
    question,
    answer,
    error,
    result,
    ask,
    press,
    release,
    stop,
    busy: phase !== "idle" && phase !== "speaking",
  };
}

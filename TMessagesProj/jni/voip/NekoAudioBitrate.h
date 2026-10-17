// Arkgram (Arkgram fork) custom group VoIP audio bitrate.
//
// Upstream 13.x moved tgcalls into the TelegramMessenger/tgcalls submodule and
// dropped the fork's `tgcalls::GroupInstanceCustomImpl::customAudioBitrate`
// static hook that used to force the Opus encoder target bitrate.
//
// The submodule's GroupInstanceDescriptor still carries
// `outgoingAudioBitrateKbit`, so the value reaches the Opus codec parameters,
// but the encoder target bitrate itself is computed inside
// `voip/webrtc/media/engine/webrtc_voice_engine.cc` (compiled into the
// `tgcalls_tp` target). That translation unit needs a way to see the value
// negotiated by the Java side, hence this tiny C++17 inline variable that both
// `tgcalls_tp` and `voipandroid` can share without touching CMakeLists.
#ifndef NEKO_AUDIO_BITRATE_H
#define NEKO_AUDIO_BITRATE_H

namespace nekogram {

// Target Opus encoder bitrate in bits per second; 0 keeps WebRTC's default
// allocation behaviour (used when no group call is active).
inline int customAudioBitrateBps = 0;

} // namespace nekogram

#endif // NEKO_AUDIO_BITRATE_H

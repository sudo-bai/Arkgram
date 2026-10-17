// Compile-time only signature stub for android.hardware.fingerprint.FingerprintManager.
//
// The framework removed FingerprintManager (and Context.FINGERPRINT_SERVICE) in API 37;
// this fork compiles with compileSdk 37 because androidx.core 1.19.0 requires it, while
// upstream still builds with compileSdk 36. Wallet's M-Q (API 23-29) unlock path still
// needs the class at compile time.
//
// This file lives in TMessagesProj/stubs, which is registered as javac's -sourcepath with
// -implicit:none, so it is used for symbol resolution only: no .class file is produced and
// nothing is packaged into the APK. At runtime the platform class from the boot class
// path is used (verified on-device only on API < 30; unverified here).
package android.hardware.fingerprint;

import android.os.CancellationSignal;
import android.os.Handler;

public class FingerprintManager {

    public static final int FINGERPRINT_ERROR_CANCELED = 5;

    public FingerprintManager() {
    }

    public boolean isHardwareDetected() {
        return false;
    }

    public boolean hasEnrolledFingerprints() {
        return false;
    }

    public void authenticate(CryptoObject crypto, CancellationSignal cancel, int flags,
                             AuthenticationCallback callback, Handler handler) {
    }

    public static class CryptoObject {
        public CryptoObject(java.security.Signature signature) {
        }
    }

    public static class AuthenticationResult {
        public CryptoObject getCryptoObject() {
            return null;
        }
    }

    public static abstract class AuthenticationCallback {
        public void onAuthenticationError(int errorCode, CharSequence errString) {
        }

        public void onAuthenticationHelp(int helpCode, CharSequence helpString) {
        }

        public void onAuthenticationSucceeded(AuthenticationResult result) {
        }

        public void onAuthenticationFailed() {
        }
    }
}

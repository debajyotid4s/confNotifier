package com.call4paper.app.feature.auth

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.auth.AuthRepository
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.remote.GoogleAuthRequest
import com.google.firebase.auth.FirebaseAuthInvalidCredentialsException
import com.google.firebase.auth.FirebaseAuthUserCollisionException
import com.google.firebase.auth.FirebaseAuthWeakPasswordException
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import javax.inject.Inject

private const val TAG = "AuthViewModel"

// Holds the email from a collision so Login can pre-fill it (separate VMs per destination)
object PendingLoginEmail { var email: String? = null }

data class AuthUiState(
    val email: String = "",
    val password: String = "",
    val confirmPassword: String = "",
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val isLoggedIn: Boolean = false,
    val suggestLogin: Boolean = false,
    val infoMessage: String? = null,
    val verificationPending: Boolean = false,
    val verificationEmail: String? = null,
    val resendCooldown: Int = 0
)

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val repo: AuthRepository,
    private val api: ApiService,
    private val tokens: TokenManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(AuthUiState(isLoggedIn = false))
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()
    private var resendJob: Job? = null

    init {
        Log.d(TAG, "init: currentUser=${repo.currentUser?.email} uid=${repo.currentUser?.uid}")
        // Don't treat Firebase user as logged in — JWT is source of truth; check it async
        viewModelScope.launch {
            val hasJwt = try { tokens.peek() != null } catch (_: Exception) { false }
            // Only mark logged in if we actually have a JWT; Splash handles routing anyway
            if (hasJwt) _uiState.value = _uiState.value.copy(isLoggedIn = true)
        }
    }

    fun onEmailChange(v: String) { _uiState.value = _uiState.value.copy(email = v, errorMessage = null, suggestLogin = false, infoMessage = null) }
    fun onPasswordChange(v: String) { _uiState.value = _uiState.value.copy(password = v, errorMessage = null, suggestLogin = false) }
    fun onConfirmPasswordChange(v: String) { _uiState.value = _uiState.value.copy(confirmPassword = v, errorMessage = null) }
    fun clearSuggestLogin() { _uiState.value = _uiState.value.copy(suggestLogin = false) }
    fun dismissVerification() { _uiState.value = _uiState.value.copy(verificationPending = false, verificationEmail = null, errorMessage = null, infoMessage = null) }

    private fun validate(isSignUp: Boolean): String? {
        val s = _uiState.value
        if (s.email.isBlank() || !android.util.Patterns.EMAIL_ADDRESS.matcher(s.email).matches()) return "Enter a valid email"
        if (s.password.length < 6) return "Password must be at least 6 characters"
        if (isSignUp && s.password != s.confirmPassword) return "Passwords do not match"
        return null
    }

    private fun startResendCooldown(seconds: Int = 120) {
        resendJob?.cancel()
        resendJob = viewModelScope.launch {
            for (i in seconds downTo 0) {
                _uiState.value = _uiState.value.copy(resendCooldown = i)
                if (i == 0) break
                delay(1000)
            }
        }
    }

    fun signUp(onSuccess: () -> Unit) {
        val err = validate(true)
        if (err != null) { _uiState.value = _uiState.value.copy(errorMessage = err); Log.w(TAG, "signUp: validation failed: $err"); return }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null, infoMessage = null)
            Log.d(TAG, "signUp: launching for ${_uiState.value.email}")
            val email = _uiState.value.email
            val res = repo.signUp(email, _uiState.value.password)
            res.onSuccess { fbUser ->
                // Link-based flow: don't mint backend JWT yet — require email verification first
                Log.i(TAG, "signUp: Firebase user created ${fbUser.email}, verification sent")
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    verificationPending = true,
                    verificationEmail = fbUser.email ?: email,
                    infoMessage = "Verification email sent to ${fbUser.email ?: email} — tap the link in your inbox, then press 'I've verified'",
                    errorMessage = null
                )
                startResendCooldown(120)
                // Keep Firebase user signed in so resend/reload works; don't call backend yet
            }.onFailure { e ->
                if (e is FirebaseAuthUserCollisionException) {
                    Log.w(TAG, "signUp: collision for ${_uiState.value.email} — suggest login")
                    PendingLoginEmail.email = _uiState.value.email
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Email already registered — try signing in", suggestLogin = true)
                } else {
                    val msg = mapError(e)
                    Log.e(TAG, "signUp: error $msg", e)
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
                }
            }
        }
    }

    fun checkVerificationAndProceed(onSuccess: () -> Unit) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            val verified = repo.reloadAndCheckVerified()
            if (!verified) {
                Log.w(TAG, "checkVerification: not yet verified")
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Not verified yet — tap the link in your email, then try again")
                return@launch
            }
            // Verified — now exchange Firebase token for backend JWT (force refresh so email_verified claim is fresh)
            try {
                val fbUser = repo.currentUser ?: throw IllegalStateException("No Firebase user")
                val fbToken = fbUser.getIdToken(true).await().token ?: throw IllegalStateException("No Firebase token")
                val phoneModel = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()
                val deviceInfo = "Android ${android.os.Build.VERSION.RELEASE} (${android.os.Build.DEVICE})"
                val resp = api.authFirebase(com.call4paper.app.data.remote.FirebaseAuthRequest(fbToken, phoneModel, deviceInfo))
                tokens.save(resp.token)
                try {
                    val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
                    api.postDevice(mapOf("fcm_token" to fcm))
                    com.google.firebase.messaging.FirebaseMessaging.getInstance().subscribeToTopic("all_users")
                } catch (_: Exception) {}
                Log.i(TAG, "checkVerification: backend JWT saved for ${resp.user.username}")
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true, verificationPending = false, verificationEmail = null, infoMessage = null)
                onSuccess()
            } catch (e: Exception) {
                Log.e(TAG, "checkVerification: backend exchange failed", e)
                val m = e.message ?: ""
                val stillNotVerified = m.contains("not verified", ignoreCase = true) || m.contains("403")
                if (stillNotVerified) {
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Still not verified — wait 10s and tap 'I've verified' again")
                } else {
                    // Likely Render cold start / network — keep pending so user can retry
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Verified, but backend is waking up — tap 'I've verified' again in a few seconds")
                }
            }
        }
    }

    fun resendVerification() {
        if (_uiState.value.resendCooldown > 0) return
        viewModelScope.launch {
            val ok = repo.resendVerification()
            if (ok) startResendCooldown(120)
            _uiState.value = _uiState.value.copy(infoMessage = if (ok) "Verification email sent — check your inbox" else "Could not send verification email — try again later", errorMessage = null)
        }
    }

    fun sendPasswordReset(onSent: () -> Unit = {}) {
        val email = _uiState.value.email.trim()
        if (email.isBlank() || !android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
            _uiState.value = _uiState.value.copy(errorMessage = "Enter your email first")
            return
        }
        if (_uiState.value.resendCooldown > 0) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null, infoMessage = null)
            val res = repo.sendPasswordReset(email)
            res.onSuccess {
                startResendCooldown(120)
                _uiState.value = _uiState.value.copy(isLoading = false, infoMessage = "Reset link sent to $email — check inbox (and Spam)")
                onSent()
            }.onFailure {
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Could not send reset link — check email and try again")
            }
        }
    }

    fun signIn(onSuccess: () -> Unit) {
        val err = validate(false)
        if (err != null) { _uiState.value = _uiState.value.copy(errorMessage = err); Log.w(TAG, "signIn: validation failed: $err"); return }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            Log.d(TAG, "signIn: launching for ${_uiState.value.email}")
            val res = repo.signIn(_uiState.value.email, _uiState.value.password)
            res.onSuccess { fbUser ->
                try {
                    val fbToken = fbUser.getIdToken(false).await().token ?: throw IllegalStateException("No Firebase token")
                    val phoneModel = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()
                    val deviceInfo = "Android ${android.os.Build.VERSION.RELEASE} (${android.os.Build.DEVICE})"
                    val resp = api.authFirebase(com.call4paper.app.data.remote.FirebaseAuthRequest(fbToken, phoneModel, deviceInfo))
                    tokens.save(resp.token)
                    try {
                        val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
                        api.postDevice(mapOf("fcm_token" to fcm))
                        com.google.firebase.messaging.FirebaseMessaging.getInstance().subscribeToTopic("all_users")
                    } catch (_: Exception) {}
                    Log.i(TAG, "signIn: backend JWT saved for ${resp.user.username}")
                    _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                    onSuccess()
                } catch (e: Exception) {
                    // Surface email-not-verified specifically; otherwise generic
                    val msg = e.message ?: ""
                    val isNotVerified = msg.contains("not verified", ignoreCase = true) || msg.contains("403")
                    Log.e(TAG, "signIn: backend exchange failed", e)
                    if (isNotVerified) {
                        // Keep Firebase user signed in so resend/reload works
                        _uiState.value = _uiState.value.copy(
                            isLoading = false,
                            verificationPending = true,
                            verificationEmail = fbUser.email,
                            errorMessage = "Email not verified — tap the link in your inbox",
                            infoMessage = "Press 'I've verified' after clicking the link, or resend"
                        )
                    } else {
                        _uiState.value = _uiState.value.copy(
                            isLoading = false,
                            errorMessage = "Signed in to Firebase but backend session failed — try again",
                            infoMessage = null
                        )
                        try { repo.signOut() } catch (_: Exception) {}
                    }
                }
            }.onFailure { e ->
                val msg = mapError(e)
                Log.e(TAG, "signIn: error $msg", e)
                // Do not leak raw token/network internals — mapError already sanitizes
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
            }
        }
    }

    fun signInWithGoogle(idToken: String, onSuccess: () -> Unit) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            Log.d(TAG, "signInWithGoogle: verifying via backend")
            try {
                val phoneModel = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()
                val deviceInfo = "Android ${android.os.Build.VERSION.RELEASE} (${android.os.Build.DEVICE})"
                val resp = api.authGoogle(GoogleAuthRequest(idToken, phoneModel, deviceInfo))
                // Do not log token
                tokens.save(resp.token)
                Log.i(TAG, "signInWithGoogle: success user=${resp.user.username}")
                // Send FCM token for push notifications
                try {
                    val fcmToken = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
                    api.postDevice(mapOf("fcm_token" to fcmToken))
                    com.google.firebase.messaging.FirebaseMessaging.getInstance().subscribeToTopic("all_users")
                    Log.d(TAG, "FCM token registered: ${fcmToken.take(12)}...")
                } catch (e: Exception) {
                    Log.w(TAG, "FCM token post failed (will retry on token refresh)", e)
                }
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            } catch (e: Exception) {
                Log.e(TAG, "signInWithGoogle: failed", e)
                // Do not surface raw exception (may contain token/network internals)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Google sign-in failed — try again")
            }
        }
    }

    // Local sign-out (used for session-expiry cleanup) — does not call backend
    fun signOut() { resendJob?.cancel(); repo.signOut(); viewModelScope.launch { tokens.clear() }; _uiState.value = AuthUiState(); Log.d(TAG, "signOut: cleared state") }

    override fun onCleared() { resendJob?.cancel(); super.onCleared() }

    private fun mapError(e: Throwable): String = when (e) {
        is FirebaseAuthWeakPasswordException -> "Password is too weak — use at least 6 characters with letters and numbers"
        is FirebaseAuthInvalidCredentialsException -> "Invalid email or password"
        is FirebaseAuthUserCollisionException -> "Email already registered — try signing in instead"
        else -> "Authentication failed — check your connection and try again"
    }
}

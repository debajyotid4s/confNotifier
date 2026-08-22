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
    val infoMessage: String? = null
)

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val repo: AuthRepository,
    private val api: ApiService,
    private val tokens: TokenManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(AuthUiState(isLoggedIn = repo.currentUser != null))
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    init {
        Log.d(TAG, "init: currentUser=${repo.currentUser?.email} uid=${repo.currentUser?.uid}")
    }

    fun onEmailChange(v: String) { _uiState.value = _uiState.value.copy(email = v, errorMessage = null, suggestLogin = false, infoMessage = null) }
    fun onPasswordChange(v: String) { _uiState.value = _uiState.value.copy(password = v, errorMessage = null, suggestLogin = false) }
    fun onConfirmPasswordChange(v: String) { _uiState.value = _uiState.value.copy(confirmPassword = v, errorMessage = null) }
    fun clearSuggestLogin() { _uiState.value = _uiState.value.copy(suggestLogin = false) }

    private fun validate(isSignUp: Boolean): String? {
        val s = _uiState.value
        if (s.email.isBlank() || !android.util.Patterns.EMAIL_ADDRESS.matcher(s.email).matches()) return "Enter a valid email"
        if (s.password.length < 6) return "Password must be at least 6 characters"
        if (isSignUp && s.password != s.confirmPassword) return "Passwords do not match"
        return null
    }

    fun signUp(onSuccess: () -> Unit) {
        val err = validate(true)
        if (err != null) { _uiState.value = _uiState.value.copy(errorMessage = err); Log.w(TAG, "signUp: validation failed: $err"); return }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            Log.d(TAG, "signUp: launching for ${_uiState.value.email}")
            val res = repo.signUp(_uiState.value.email, _uiState.value.password)
            res.onSuccess { fbUser ->
                try {
                    val fbToken = fbUser.getIdToken(false).await().token ?: throw IllegalStateException("No Firebase token")
                    val phoneModel = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()
                    val deviceInfo = "Android ${android.os.Build.VERSION.RELEASE} (${android.os.Build.DEVICE})"
                    val resp = api.authFirebase(com.call4paper.app.data.remote.FirebaseAuthRequest(fbToken, phoneModel, deviceInfo))
                    tokens.save(resp.token)
                    try { val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await(); api.postDevice(mapOf("fcm_token" to fcm)) } catch (_: Exception) {}
                    Log.i(TAG, "signUp: backend JWT saved for ${resp.user.username}")
                    _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                    onSuccess()
                } catch (e: Exception) {
                    Log.e(TAG, "signUp: backend exchange failed", e)
                    // Do not navigate — user has Firebase account but no backend session; surface error
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Account created but session failed — try signing in again")
                    try { repo.signOut() } catch (_: Exception) {}
                }
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

    fun resendVerification() {
        viewModelScope.launch {
            val ok = repo.resendVerification()
            _uiState.value = _uiState.value.copy(infoMessage = if (ok) "Verification email sent — check your inbox" else "Could not send verification email")
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
                    try { val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await(); api.postDevice(mapOf("fcm_token" to fcm)) } catch (_: Exception) {}
                    Log.i(TAG, "signIn: backend JWT saved for ${resp.user.username}")
                    _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                    onSuccess()
                } catch (e: Exception) {
                    // Surface email-not-verified specifically; otherwise generic
                    val msg = e.message ?: ""
                    val isNotVerified = msg.contains("not verified", ignoreCase = true) || msg.contains("403")
                    Log.e(TAG, "signIn: backend exchange failed", e)
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        errorMessage = if (isNotVerified) "Email not verified — check your inbox and try again" else "Signed in to Firebase but backend session failed — try again",
                        infoMessage = if (isNotVerified) "Tap resend to get a new verification email" else null
                    )
                    try { repo.signOut() } catch (_: Exception) {}
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
    fun signOut() { repo.signOut(); viewModelScope.launch { tokens.clear() }; _uiState.value = AuthUiState(); Log.d(TAG, "signOut: cleared state") }

    private fun mapError(e: Throwable): String = when (e) {
        is FirebaseAuthWeakPasswordException -> "Password is too weak — use at least 6 characters with letters and numbers"
        is FirebaseAuthInvalidCredentialsException -> "Invalid email or password"
        is FirebaseAuthUserCollisionException -> "Email already registered — try signing in instead"
        else -> "Authentication failed — check your connection and try again"
    }
}

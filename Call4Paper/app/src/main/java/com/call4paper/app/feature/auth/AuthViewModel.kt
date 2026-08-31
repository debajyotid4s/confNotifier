package com.call4paper.app.feature.auth

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.auth.AuthRepository
import com.call4paper.app.data.local.TokenManager
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.remote.AuthRequest
import com.call4paper.app.data.remote.AuthResponse
import com.google.firebase.auth.FirebaseAuthInvalidCredentialsException
import com.google.firebase.auth.FirebaseAuthUserCollisionException
import com.google.firebase.auth.FirebaseAuthWeakPasswordException
import androidx.lifecycle.SavedStateHandle
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import javax.inject.Inject

private const val TAG = "AuthViewModel"

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
    private val tokens: TokenManager,
    private val savedStateHandle: SavedStateHandle
) : ViewModel() {

    private val _uiState = MutableStateFlow(AuthUiState(isLoggedIn = false))
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()
    private var resendJob: Job? = null
    private var googleJob: Job? = null

    init {
        Log.d(TAG, "init: currentUser=${repo.currentUser?.email} uid=${repo.currentUser?.uid}")
        viewModelScope.launch {
            val hasJwt = try { tokens.peek() != null } catch (_: Exception) { false }
            if (hasJwt) _uiState.value = _uiState.value.copy(isLoggedIn = true)
        }
    }

    fun onEmailChange(v: String) { _uiState.value = _uiState.value.copy(email = v, errorMessage = null, suggestLogin = false, infoMessage = null) }
    fun consumePendingLoginEmail(): String? = savedStateHandle.remove<String>("pendingLoginEmail")
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

    // -------------------------------------------------------------------------
    // Shared session routine — token exchange + device registration
    // -------------------------------------------------------------------------

    private data class SessionInfo(val provider: String, val idToken: String)

    private suspend fun performSession(info: SessionInfo): AuthResponse {
        val phoneModel = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()
        val deviceInfo = "Android ${android.os.Build.VERSION.RELEASE} (${android.os.Build.DEVICE})"
        val resp = api.login(AuthRequest(provider = info.provider, id_token = info.idToken, phone_model = phoneModel, device_info = deviceInfo))
        tokens.save(resp.token)
        registerDevice()
        Log.i(TAG, "performSession: ${info.provider} login success user=${resp.user.username}")
        return resp
    }

    private suspend fun registerDevice() {
        try {
            val fcm = com.google.firebase.messaging.FirebaseMessaging.getInstance().token.await()
            api.postDevice(mapOf("fcm_token" to fcm))
            com.google.firebase.messaging.FirebaseMessaging.getInstance().subscribeToTopic("all_users")
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { Log.w(TAG, "registerDevice failed", e) }
    }

    private fun parseServerError(e: Throwable): String {
        return try {
            if (e is retrofit2.HttpException) {
                val body = e.response()?.errorBody()?.string() ?: ""
                val json = org.json.JSONObject(body)
                json.optString("detail", e.message() ?: "Server error")
            } else {
                "Authentication failed — check your connection and try again"
            }
        } catch (_: Exception) {
            "Authentication failed — check your connection and try again"
        }
    }

    private fun isNotVerifiedError(e: Throwable): Boolean {
        val msg = e.message ?: ""
        return msg.contains("not verified", ignoreCase = true) || msg.contains("403")
    }

    // -------------------------------------------------------------------------
    // Sign-up
    // -------------------------------------------------------------------------

    fun signUp(onSuccess: () -> Unit) {
        val err = validate(true)
        if (err != null) { _uiState.value = _uiState.value.copy(errorMessage = err); Log.w(TAG, "signUp: validation failed: $err"); return }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null, infoMessage = null)
            val email = _uiState.value.email
            val res = repo.signUp(email, _uiState.value.password)
            res.onSuccess { fbUser ->
                Log.i(TAG, "signUp: Firebase user created ${fbUser.email}, verification sent")
                _uiState.value = _uiState.value.copy(
                    isLoading = false, verificationPending = true,
                    verificationEmail = fbUser.email ?: email,
                    infoMessage = "Verification email sent to ${fbUser.email ?: email} — tap the link in your inbox, then press 'I've verified'",
                    errorMessage = null
                )
                startResendCooldown(120)
            }.onFailure { e ->
                if (e is CancellationException) throw e
                if (e is FirebaseAuthUserCollisionException) {
                    savedStateHandle["pendingLoginEmail"] = _uiState.value.email
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Email already registered — try signing in", suggestLogin = true)
                } else {
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = mapError(e))
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Sign-in (Firebase email/password)
    // -------------------------------------------------------------------------

    fun signIn(onSuccess: () -> Unit) {
        val err = validate(false)
        if (err != null) { _uiState.value = _uiState.value.copy(errorMessage = err); Log.w(TAG, "signIn: validation failed: $err"); return }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            val res = repo.signIn(_uiState.value.email, _uiState.value.password)
            res.onSuccess { fbUser ->
                try {
                    val fbToken = fbUser.getIdToken(false).await().token ?: throw IllegalStateException("No Firebase token")
                    performSession(SessionInfo("firebase", fbToken))
                    _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                    onSuccess()
                } catch (e: CancellationException) { throw e }
                catch (e: retrofit2.HttpException) {
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = parseServerError(e))
                } catch (e: Exception) {
                    if (isNotVerifiedError(e)) {
                        _uiState.value = _uiState.value.copy(
                            isLoading = false, verificationPending = true, verificationEmail = fbUser.email,
                            errorMessage = "Email not verified — tap the link in your inbox",
                            infoMessage = "Press 'I've verified' after clicking the link, or resend"
                        )
                    } else {
                        _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Signed in to Firebase but backend session failed — try again")
                        try { repo.signOut() } catch (e: Exception) { Log.w(TAG, "signOut failed", e) }
                    }
                }
            }.onFailure { e ->
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = mapError(e))
            }
        }
    }

    // -------------------------------------------------------------------------
    // Sign-in (Google)
    // -------------------------------------------------------------------------

    fun onGoogleTokenUnavailable() {
        Log.w(TAG, "Google credential unavailable — no account on device or Play Services outdated")
        _uiState.value = _uiState.value.copy(
            isLoading = false,
            errorMessage = "No Google account found on device — add a Google account or update Play Services, then try again"
        )
    }

    fun startGoogleSignIn(context: android.content.Context, onSuccess: () -> Unit) {
        if (googleJob?.isActive == true) return
        googleJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            val token = com.call4paper.app.feature.auth.getGoogleIdToken(context)
            if (token == null) {
                onGoogleTokenUnavailable()
                return@launch
            }
            try {
                performSession(SessionInfo("google", token))
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            } catch (e: CancellationException) { throw e }
            catch (e: retrofit2.HttpException) {
                Log.e(TAG, "startGoogleSignIn HttpException ${e.code()}", e)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = parseServerError(e))
            } catch (e: Exception) {
                Log.e(TAG, "startGoogleSignIn failed: ${e::class.simpleName}: ${e.message}", e)
                val msg = when (e) {
                    is java.net.SocketTimeoutException, is java.net.ConnectException, is java.io.IOException ->
                        "Network timeout — backend is waking up (Render free tier). Try again in 10s. (${e.message?.take(60)})"
                    else -> e.message?.takeIf { it.isNotBlank() } ?: "Google sign-in failed — try again"
                }
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
            }
        }
    }

    fun signInWithGoogle(idToken: String, onSuccess: () -> Unit) {
        if (googleJob?.isActive == true) return
        googleJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            try {
                performSession(SessionInfo("google", idToken))
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            } catch (e: CancellationException) { throw e }
            catch (e: retrofit2.HttpException) {
                Log.e(TAG, "signInWithGoogle HttpException ${e.code()}", e)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = parseServerError(e))
            } catch (e: Exception) {
                Log.e(TAG, "signInWithGoogle failed: ${e::class.simpleName}: ${e.message}", e)
                val msg = when (e) {
                    is java.net.SocketTimeoutException, is java.net.ConnectException, is java.io.IOException ->
                        "Network timeout — backend is waking up (Render free tier). Try again in 10s. (${e.message?.take(60)})"
                    else -> e.message?.takeIf { it.isNotBlank() } ?: "Google sign-in failed — try again"
                }
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
            }
        }
    }

    // -------------------------------------------------------------------------
    // Post-verification sign-in
    // -------------------------------------------------------------------------

    fun checkVerificationAndProceed(onSuccess: () -> Unit) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            val verified = repo.reloadAndCheckVerified()
            if (!verified) {
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Not verified yet — tap the link in your email, then try again")
                return@launch
            }
            try {
                val fbUser = repo.currentUser ?: throw IllegalStateException("No Firebase user")
                val fbToken = fbUser.getIdToken(true).await().token ?: throw IllegalStateException("No Firebase token")
                performSession(SessionInfo("firebase", fbToken))
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true, verificationPending = false, verificationEmail = null, infoMessage = null)
                onSuccess()
            } catch (e: CancellationException) { throw e }
            catch (e: retrofit2.HttpException) {
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = parseServerError(e))
            } catch (e: Exception) {
                if (isNotVerifiedError(e)) {
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Still not verified — wait 10s and tap 'I've verified' again")
                } else {
                    _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Verified, but backend is waking up — tap 'I've verified' again in a few seconds")
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Misc
    // -------------------------------------------------------------------------

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
            _uiState.value = _uiState.value.copy(errorMessage = "Enter your email first"); return
        }
        if (_uiState.value.resendCooldown > 0) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null, infoMessage = null)
            val res = repo.sendPasswordReset(email)
            res.onSuccess {
                startResendCooldown(120)
                _uiState.value = _uiState.value.copy(isLoading = false, infoMessage = "Reset link sent to $email — check inbox (and Spam)")
                onSent()
            }.onFailure { e ->
                if (e is CancellationException) throw e
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = "Could not send reset link — check email and try again")
            }
        }
    }

    fun signOut() { resendJob?.cancel(); repo.signOut(); viewModelScope.launch { tokens.clear() }; _uiState.value = AuthUiState() }

    override fun onCleared() { resendJob?.cancel(); super.onCleared() }

    private fun mapError(e: Throwable): String = when (e) {
        is FirebaseAuthWeakPasswordException -> "Password is too weak — use at least 6 characters with letters and numbers"
        is FirebaseAuthInvalidCredentialsException -> "Invalid email or password"
        is FirebaseAuthUserCollisionException -> "Email already registered — try signing in instead"
        else -> "Authentication failed — check your connection and try again"
    }
}

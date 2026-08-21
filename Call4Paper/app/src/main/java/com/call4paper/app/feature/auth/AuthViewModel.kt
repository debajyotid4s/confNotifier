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
import javax.inject.Inject

private const val TAG = "AuthViewModel"

data class AuthUiState(
    val email: String = "",
    val password: String = "",
    val confirmPassword: String = "",
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val isLoggedIn: Boolean = false
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

    fun onEmailChange(v: String) { _uiState.value = _uiState.value.copy(email = v, errorMessage = null) }
    fun onPasswordChange(v: String) { _uiState.value = _uiState.value.copy(password = v, errorMessage = null) }
    fun onConfirmPasswordChange(v: String) { _uiState.value = _uiState.value.copy(confirmPassword = v, errorMessage = null) }

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
            res.onSuccess {
                Log.i(TAG, "signUp: navigated to feed for ${it.email}")
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            }.onFailure { e ->
                val msg = mapError(e)
                Log.e(TAG, "signUp: error $msg", e)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
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
            res.onSuccess {
                Log.i(TAG, "signIn: navigated to feed for ${it.email}")
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            }.onFailure { e ->
                val msg = mapError(e)
                Log.e(TAG, "signIn: error $msg", e)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = msg)
            }
        }
    }

    fun signInWithGoogle(idToken: String, onSuccess: () -> Unit) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            Log.d(TAG, "signInWithGoogle: verifying via backend")
            try {
                val resp = api.authGoogle(GoogleAuthRequest(idToken))
                // Do not log token
                tokens.save(resp.token)
                Log.i(TAG, "signInWithGoogle: success user=${resp.user.username}")
                _uiState.value = _uiState.value.copy(isLoading = false, isLoggedIn = true)
                onSuccess()
            } catch (e: Exception) {
                Log.e(TAG, "signInWithGoogle: failed", e)
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = e.message ?: "Google sign-in failed")
            }
        }
    }

    fun signOut() { repo.signOut(); viewModelScope.launch { tokens.clear() }; _uiState.value = AuthUiState(); Log.d(TAG, "signOut: cleared state") }

    private fun mapError(e: Throwable): String = when (e) {
        is FirebaseAuthWeakPasswordException -> "Weak password: ${e.reason}"
        is FirebaseAuthInvalidCredentialsException -> "Invalid email or password"
        is FirebaseAuthUserCollisionException -> "Email already registered"
        else -> e.message ?: "Authentication failed"
    }
}

/**
 * QuickNest Universal Inline Form Validation Engine
 * 
 * - Disables native browser popup tooltips (novalidate)
 * - Prevents JS alert() / Notice modals for form errors
 * - Displays field-specific inline error messages directly below inputs
 * - Highlights invalid inputs with red borders
 * - Automatically clears errors as the user types/corrects input
 * - Shows all errors simultaneously
 * - Focuses and scrolls to the first invalid field on submit failure
 */

(function () {
  'use strict';

  // Override standard alert if called for validation (safety layer)
  const nativeAlert = window.alert;
  window.alert = function (msg) {
    if (typeof msg === 'string' && (
      msg.toLowerCase().includes('must be') ||
      msg.toLowerCase().includes('required') ||
      msg.toLowerCase().includes('invalid') ||
      msg.toLowerCase().includes('enter a valid')
    )) {
      console.warn('[FormValidation] Prevented popup alert:', msg);
      return;
    }
    return nativeAlert.apply(this, arguments);
  };

  /**
   * Helper to fetch human-friendly field name from label or placeholder or name attribute
   */
  function getFieldLabel(input) {
    if (input.dataset.label) return input.dataset.label;
    
    // Check for associated label element
    if (input.id) {
      const labelEl = document.querySelector(`label[for="${input.id}"]`);
      if (labelEl) {
        let text = labelEl.innerText.replace(/\*/g, '').trim();
        text = text.replace(/:\s*$/, '').trim();
        if (text) return text;
      }
    }
    
    // Check parent label
    const parentLabel = input.closest('label');
    if (parentLabel) {
      let text = parentLabel.innerText.replace(/\*/g, '').trim();
      text = text.replace(/:\s*$/, '').trim();
      if (text) return text;
    }

    // Fallback to placeholder or name
    if (input.placeholder && input.placeholder.length < 30) {
      return input.placeholder.trim();
    }
    
    if (input.name) {
      const formatted = input.name.replace(/_/g, ' ');
      return formatted.charAt(0).toUpperCase() + formatted.slice(1);
    }
    
    return 'This field';
  }

  /**
   * Validates a single input element and returns error string (or empty if valid)
   */
  function validateField(input) {
    // Ignore hidden, disabled, or submit/button inputs
    if (input.type === 'hidden' || input.disabled || input.type === 'submit' || input.type === 'button' || input.type === 'reset') {
      return '';
    }

    // Skip search fields in table filters if they are optional GET forms
    const form = input.form;
    if (form && form.method.toUpperCase() === 'GET' && form.classList.contains('items-search')) {
      return '';
    }

    const val = input.value ? input.value.trim() : '';
    const name = (input.name || '').toLowerCase();
    const type = (input.type || '').toLowerCase();
    const tagName = input.tagName.toUpperCase();

    // 1. Required Check
    const isRequired = input.hasAttribute('required') || input.dataset.ruleRequired === 'true';
    if (isRequired) {
      if (tagName === 'SELECT') {
        if (!val || val === '') {
          if (input.dataset.msgRequired) return input.dataset.msgRequired;
          return 'This field is required.';
        }
      } else if (type === 'checkbox') {
        if (!input.checked) {
          if (input.dataset.msgRequired) return input.dataset.msgRequired;
          return 'This field is required.';
        }
      } else if (!val) {
        if (input.dataset.msgRequired) return input.dataset.msgRequired;
        return 'This field is required.';
      }
    }

    // If empty and not required, pass
    if (!val) return '';

    // If it is a SELECT element, only the required check above applies (no phone/date/number/pan validation)
    if (tagName === 'SELECT') {
      return '';
    }

    // 2. Email Validation (INPUT fields only)
    const isEmailField = tagName === 'INPUT' && (
      type === 'email' ||
      name === 'email' ||
      name.endsWith('_email') ||
      input.dataset.ruleEmail === 'true'
    );
    if (isEmailField) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(val)) {
        if (input.dataset.msgEmail) return input.dataset.msgEmail;
        return 'Please enter a valid email address.';
      }
    }

    // 3. Contact / Mobile / Phone Number Validation (Actual phone INPUT fields only)
    const isPhoneField = tagName === 'INPUT' && (
      type === 'tel' ||
      name === 'contact_number' ||
      name === 'coordinator_contact' ||
      name === 'reference_contact' ||
      name === 'mobile' ||
      name === 'mobile_number' ||
      name === 'phone' ||
      name === 'phone_number' ||
      name === 'user_phone' ||
      name === 'donor_contact' ||
      name.startsWith('contact_number_') ||
      name.endsWith('_contact') ||
      name.endsWith('_phone') ||
      name.endsWith('_mobile') ||
      input.dataset.rulePhone === 'true'
    );
    if (isPhoneField) {
      const cleanDigits = val.replace(/\D/g, '');
      if (cleanDigits.length !== 10 || !/^\d{10}$/.test(val)) {
        if (input.dataset.msgPhone) return input.dataset.msgPhone;
        if (name.includes('reference')) {
          return 'Reference contact number must be exactly 10 digits.';
        }
        return 'Contact number must be exactly 10 digits.';
      }
    }

    // 4. PAN Number Validation (INPUT fields only)
    const isPanField = tagName === 'INPUT' && (
      name === 'pan' ||
      name === 'pan_number' ||
      name.endsWith('_pan') ||
      input.dataset.rulePan === 'true'
    );
    if (isPanField) {
      const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/i;
      if (!panRegex.test(val)) {
        return 'Please enter a valid PAN number.';
      }
    }

    // 5. Date Validation & Specific Rules (Date INPUT fields only)
    const isDateField = tagName === 'INPUT' && (
      type === 'date' ||
      name === 'date_of_birth' ||
      name === 'dob' ||
      name === 'proposed_date' ||
      name === 'start_date' ||
      name === 'end_date' ||
      name === 'new_return_date' ||
      input.dataset.ruleDate === 'true'
    );
    if (isDateField) {
      const d = new Date(val);
      if (isNaN(d.getTime())) {
        return 'Please enter a valid date.';
      }

      const today = new Date();
      today.setHours(0, 0, 0, 0);

      // Date of Birth rules
      if (name.includes('dob') || name.includes('date_of_birth') || input.dataset.ruleDob === 'true') {
        const inputDate = new Date(val);
        inputDate.setHours(0,0,0,0);
        if (inputDate > today) {
          return 'Date of birth cannot be in the future.';
        }

        // Donor min age check (18 years)
        if (form && (form.action.includes('be_donor') || form.action.includes('be-donor') || window.location.pathname.includes('be-donor'))) {
          let age = today.getFullYear() - inputDate.getFullYear();
          const m = today.getMonth() - inputDate.getMonth();
          if (m < 0 || (m === 0 && today.getDate() < inputDate.getDate())) {
            age--;
          }
          if (age < 18) {
            return 'You must be at least 18 years old to register as a donor.';
          }
        }
      }

      // Camp proposed date rules (must be in future)
      if (name.includes('proposed_date') || input.dataset.ruleFutureDate === 'true') {
        const inputDate = new Date(val);
        inputDate.setHours(0,0,0,0);
        if (inputDate < today) {
          return 'Proposed date must be in the future.';
        }
      }
    }

    // 6. Number / Amount / Quantity Validation (INPUT fields only)
    const isNumberField = tagName === 'INPUT' && (
      type === 'number' ||
      name === 'units_required' ||
      name === 'expected_donors' ||
      name === 'price' ||
      name === 'deposit' ||
      name === 'price_per_day' ||
      name === 'total_quantity' ||
      name === 'amount' ||
      name === 'donation_amount' ||
      input.dataset.ruleNumber === 'true'
    );
    if (isNumberField) {
      const numVal = parseFloat(val);
      if (isNaN(numVal)) {
        return 'Please enter a valid amount.';
      }
      
      const minAttr = input.getAttribute('min');
      if (minAttr !== null && !isNaN(parseFloat(minAttr))) {
        const minVal = parseFloat(minAttr);
        if (numVal < minVal) {
          if (name.includes('expected_donors')) {
            return 'Expected number of donors must be greater than zero.';
          }
          if (name.includes('units')) {
            return 'Units required must be at least 1.';
          }
          return `Please enter a valid amount (minimum ${minVal}).`;
        }
      }
    }

    // 7. Password rules & Password matching
    if (type === 'password' || name === 'password' || name === 'new_password' || name === 'confirm_password' || name === 'password_confirm') {
      if (val.length < 6) {
        return 'Password must be at least 6 characters long.';
      }

      if (name === 'confirm_password' || name === 'password_confirm') {
        const pwField = form ? (form.querySelector('input[name="password"]') || form.querySelector('input[name="new_password"]')) : null;
        if (pwField && pwField.value !== val) {
          return 'Passwords do not match.';
        }
      }
    }

    return '';
  }

  /**
   * Renders an error message element directly below the specified input
   */
  function showError(input, msgText) {
    input.classList.add('is-invalid');
    input.setAttribute('aria-invalid', 'true');

    // Find existing error container or create one
    let errorContainer = null;

    // Check if error-msg element already exists in immediate parent / next sibling
    const parent = input.parentElement;
    if (parent) {
      errorContainer = parent.querySelector('.field-error-msg, .invalid-feedback, .error-msg');
    }

    if (!errorContainer && parent) {
      // Create new error-msg container
      errorContainer = document.createElement('div');
      errorContainer.className = 'field-error-msg';
      
      // Append right after input (or after input's parent if input is in an input group)
      if (input.nextSibling) {
        parent.insertBefore(errorContainer, input.nextSibling);
      } else {
        parent.appendChild(errorContainer);
      }
    }

    if (errorContainer) {
      errorContainer.style.display = 'flex';
      errorContainer.style.color = '#dc3545';
      errorContainer.innerHTML = `<i class="fas fa-exclamation-circle" style="color: #dc3545 !important;"></i> <span style="color: #dc3545 !important;">${msgText}</span>`;
    }
  }

  /**
   * Clears error styling and message element for an input
   */
  function clearError(input) {
    input.classList.remove('is-invalid');
    input.removeAttribute('aria-invalid');

    const parent = input.parentElement;
    if (parent) {
      const errorContainer = parent.querySelector('.field-error-msg, .invalid-feedback, .error-msg');
      if (errorContainer) {
        // If it was statically rendered by Django, we can hide or clear it
        errorContainer.innerHTML = '';
        errorContainer.style.display = 'none';
      }
    }
  }

  /**
   * Form submit handler to validate all fields in a form
   */
  function handleFormSubmit(e) {
    const form = e.target;
    if (!form || form.tagName !== 'FORM') return;

    // Skip GET search forms
    if (form.method.toUpperCase() === 'GET' && form.classList.contains('items-search')) {
      return;
    }

    const inputs = form.querySelectorAll('input, select, textarea');
    let firstInvalidInput = null;
    let hasError = false;

    inputs.forEach(input => {
      const error = validateField(input);
      if (error) {
        showError(input, error);
        hasError = true;
        if (!firstInvalidInput) {
          firstInvalidInput = input;
        }
      } else {
        clearError(input);
      }
    });

    if (hasError) {
      e.preventDefault();
      e.stopPropagation();

      if (firstInvalidInput) {
        firstInvalidInput.focus();
        firstInvalidInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }

  /**
   * Real-time input listener to clear error as user types/edits
   */
  function handleInputEvent(e) {
    const input = e.target;
    if (!input || !['INPUT', 'SELECT', 'TEXTAREA'].includes(input.tagName)) return;

    if (input.classList.contains('is-invalid')) {
      const error = validateField(input);
      if (!error) {
        clearError(input);
      } else {
        showError(input, error);
      }
    }
  }

  /**
   * Initialize validation on all forms in the document
   */
  function initFormValidation() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
      // Enable novalidate so browser popups don't trigger
      form.setAttribute('novalidate', 'true');
    });

    document.addEventListener('submit', handleFormSubmit, true);
    document.addEventListener('input', handleInputEvent, true);
    document.addEventListener('change', handleInputEvent, true);
    document.addEventListener('blur', handleInputEvent, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFormValidation);
  } else {
    initFormValidation();
  }

  // Export for global access if needed
  window.QuickNestValidation = {
    validateField,
    showError,
    clearError,
    init: initFormValidation
  };
})();

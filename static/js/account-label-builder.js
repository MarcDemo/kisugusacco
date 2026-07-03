(function () {
  const allowedAccountLabel = /^[A-Za-z0-9 _.-]+$/;
  const maxLabelLength = 20;

  function normalizeLabel(value) {
    return (value || '').trim().replace(/\s+/g, ' ');
  }

  function splitLabels(value) {
    return (value || '')
      .replace(/\r/g, '\n')
      .split('\n')
      .map(normalizeLabel)
      .filter(Boolean);
  }

  function setError(input, errorElement, message) {
    input.classList.toggle('is-invalid', Boolean(message));
    if (!errorElement) return;
    errorElement.textContent = message || '';
    errorElement.classList.toggle('d-none', !message);
  }

  function labelExists(labels, label) {
    const key = label.toLowerCase();
    return labels.some(function (existingLabel) {
      return existingLabel.toLowerCase() === key;
    });
  }

  function renderLabels(labels, hiddenInput, listElement, emptyElement) {
    hiddenInput.value = labels.join('\n');
    listElement.innerHTML = '';

    labels.forEach(function (label, index) {
      const item = document.createElement('span');
      item.className = 'badge text-bg-light border text-dark d-inline-flex align-items-center gap-2 px-3 py-2';

      const text = document.createElement('span');
      text.textContent = 'Account ' + label;
      item.appendChild(text);

      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'btn-close';
      removeButton.dataset.removeAccountLabel = String(index);
      removeButton.setAttribute('aria-label', 'Remove account ' + label);
      removeButton.title = 'Remove account';
      item.appendChild(removeButton);

      listElement.appendChild(item);
    });

    if (emptyElement) {
      emptyElement.classList.toggle('d-none', labels.length > 0);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-account-label-builder]').forEach(function (builder) {
      const hiddenInput = builder.querySelector('input[name="account_labels"]');
      const entryInput = builder.querySelector('[data-account-label-entry]');
      const addButton = builder.querySelector('[data-add-account-label]');
      const listElement = builder.querySelector('[data-account-label-list]');
      const emptyElement = builder.querySelector('[data-account-label-empty]');
      const errorElement = builder.querySelector('[data-account-label-error]');

      if (!hiddenInput || !entryInput || !addButton || !listElement) return;

      const existingLabels = Array.from(document.querySelectorAll('[data-existing-account-label]'))
        .map(function (element) {
          return normalizeLabel(element.dataset.existingAccountLabel);
        })
        .filter(Boolean);
      const labels = splitLabels(hiddenInput.value);

      function addLabel() {
        const label = normalizeLabel(entryInput.value);

        if (!label) {
          setError(entryInput, errorElement, 'Enter an account label first.');
          entryInput.focus();
          return false;
        }

        if (label.length > maxLabelLength) {
          setError(entryInput, errorElement, 'Savings account labels must be 20 characters or fewer.');
          entryInput.focus();
          return false;
        }

        if (!allowedAccountLabel.test(label)) {
          setError(entryInput, errorElement, 'Savings account labels can only contain letters, numbers, spaces, hyphens, underscores, or periods.');
          entryInput.focus();
          return false;
        }

        if (labelExists(labels, label) || labelExists(existingLabels, label)) {
          setError(entryInput, errorElement, 'That savings account has already been added.');
          entryInput.focus();
          return false;
        }

        labels.push(label);
        entryInput.value = '';
        setError(entryInput, errorElement, '');
        renderLabels(labels, hiddenInput, listElement, emptyElement);
        entryInput.focus();
        return true;
      }

      addButton.addEventListener('click', addLabel);

      entryInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          addLabel();
        }
      });

      entryInput.addEventListener('input', function () {
        if (errorElement && errorElement.textContent) {
          setError(entryInput, errorElement, '');
        }
      });

      listElement.addEventListener('click', function (event) {
        const removeButton = event.target.closest('[data-remove-account-label]');
        if (!removeButton) return;

        const index = Number(removeButton.dataset.removeAccountLabel);
        if (Number.isInteger(index)) {
          labels.splice(index, 1);
          renderLabels(labels, hiddenInput, listElement, emptyElement);
        }
      });

      const form = builder.closest('form');
      if (form) {
        form.addEventListener('submit', function (event) {
          if (normalizeLabel(entryInput.value)) {
            event.preventDefault();
            setError(entryInput, errorElement, 'Press Add Account before saving this user.');
            entryInput.focus();
          }
        });
      }

      renderLabels(labels, hiddenInput, listElement, emptyElement);
    });
  });
})();

// The Zoho Lead form as shown on the "Convert to Lead" screen in demo mode.
// These are the fields of the client's testing Zoho CRM (Leads module), with Zoho's own labels.

import type { ZohoFieldKind } from '../api'

export type DemoZohoField = {
  api_name: string
  label: string
  kind: ZohoFieldKind
  required?: boolean
  options?: string[]
  custom?: boolean
}

const text = (api_name: string, label: string, extra: Partial<DemoZohoField> = {}): DemoZohoField => ({
  api_name,
  label,
  kind: 'text',
  ...extra,
})

export const ZOHO_LEAD_FIELDS: DemoZohoField[] = [
  text('Company', 'Company'),
  text('First_Name', 'First Name'),
  text('Last_Name', 'Last Name', { required: true }),
  text('Designation', 'Designation'),
  { api_name: 'Email', label: 'Email', kind: 'email' },
  { api_name: 'Phone', label: 'Phone', kind: 'phone' },
  text('Fax', 'Fax'),
  { api_name: 'Mobile', label: 'Mobile', kind: 'phone' },
  { api_name: 'Website', label: 'Website', kind: 'url' },
  {
    api_name: 'Lead_Source',
    label: 'Lead Source',
    kind: 'select',
    options: [
      'Advertisement',
      'Cold Call',
      'Employee Referral',
      'External Referral',
      'Online Store',
      'Partner',
      'Public Relations',
      'Sales Email Alias',
      'Seminar Partner',
      'Internal Seminar',
      'Trade Show',
      'Web Download',
      'Web Research',
      'Chat',
      'X (Twitter)',
      'Facebook',
    ],
  },
  {
    api_name: 'Lead_Status',
    label: 'Lead Status',
    kind: 'select',
    options: [
      'Attempted to Contact',
      'Contact in Future',
      'Contacted',
      'Junk Lead',
      'Lost Lead',
      'Not Contacted',
      'Pre-Qualified',
      'Not Qualified',
    ],
  },
  {
    api_name: 'Industry',
    label: 'Industry',
    kind: 'select',
    options: ['ERP', 'Government/Military', 'Large Enterprise', 'Service Provider', 'Small/Medium Enterprise', 'Wireless Industry'],
  },
  { api_name: 'No_of_Employees', label: 'No of Employees', kind: 'integer' },
  { api_name: 'Annual_Revenue', label: 'Annual Revenue', kind: 'decimal' },
  { api_name: 'Rating', label: 'Rating', kind: 'select', options: ['Acquired', 'Active', 'Market Failed', 'Project Cancelled', 'Shut Down'] },
  { api_name: 'Email_Opt_Out', label: 'Email Opt Out', kind: 'boolean' },
  text('Skype_ID', 'Skype ID'),
  { api_name: 'Salutation', label: 'Salutation', kind: 'select', options: ['Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.'] },
  { api_name: 'Secondary_Email', label: 'Secondary Email', kind: 'email' },
  text('Twitter', 'Twitter'),
  { api_name: 'Description', label: 'Description', kind: 'textarea' },
  text('City', 'Address - City'),
  { api_name: 'Country', label: 'Address - Country / Region', kind: 'select', options: ['India', 'United Arab Emirates', 'United States', 'United Kingdom'] },
  text('Flat_House_No_Building_Apartment_Name', 'Address - Flat / House No./ Building / Apartment Name'),
  text('State', 'Address - State / Province'),
  text('Street', 'Address - Street Address'),
  text('Zip_Code', 'Address - Zip / Postal Code'),
  { api_name: 'Loan_Type', label: 'Loan Type', kind: 'select', options: ['LAP', 'Business Loan', 'Working Capital'], custom: true },
  { api_name: 'Assigned_to', label: 'Assigned to', kind: 'select', options: ['Ravi Kumar', 'Priya Sharma'], custom: true },
]
